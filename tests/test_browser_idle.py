"""Browser idle hooks stay advisory, cancel stale work and isolate concurrent turns."""

import concurrent.futures
import importlib.util
import io
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch


root = Path(__file__).resolve().parents[1]
script = root / "chrome/.local/libexec/chatgpt-browser-idle.py"
spec = importlib.util.spec_from_file_location("browser_idle", script)
idle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(idle)


def event(kind, *, session="session-a", turn="turn-a", call="call-a", tool="mcp__node_repl__js"):
    return {"hook_event_name": kind, "session_id": session, "turn_id": turn,
            "tool_use_id": call, "tool_name": tool}


class IdleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "state/idle.sqlite3"
        self.db = idle.connect(self.path)
        self.addCleanup(self.db.close)

    def complete(self, **ids):
        idle.update(self.db, event("PreToolUse", **ids))
        return idle.update(self.db, event("PostToolUse", **ids))

    def test_five_minute_boundary_and_only_one_reminder(self):
        with patch.object(idle.time, "monotonic", return_value=10):
            key = self.complete()
        with patch.object(idle.time, "monotonic", return_value=309):
            self.assertEqual(idle.remaining(self.db, key, idle.IDLE_SECONDS), 1)
        with patch.object(idle.time, "monotonic", return_value=310):
            self.assertEqual(idle.remaining(self.db, key, idle.IDLE_SECONDS), 0)
            self.assertIsNone(idle.remaining(self.db, key, idle.IDLE_SECONDS))

    def test_new_activity_cancels_old_timer_and_duplicate_posts_are_ignored(self):
        old = self.complete()
        self.assertIsNone(idle.update(self.db, event("PostToolUse")))
        self.assertIsNone(idle.update(self.db, event("PreToolUse", call="new")))
        self.assertIsNone(idle.remaining(self.db, old, 0))
        new = idle.update(self.db, event("PostToolUse", call="new"))
        self.assertEqual(idle.remaining(self.db, new, 0), 0)

    def test_parallel_calls_wait_for_all_completions(self):
        idle.update(self.db, event("PreToolUse", call="slow"))
        idle.update(self.db, event("PreToolUse", call="fast"))
        fast = idle.update(self.db, event("PostToolUse", call="fast"))
        self.assertIsNone(idle.remaining(self.db, fast, 0))
        slow = idle.update(self.db, event("PostToolUse", call="slow"))
        self.assertIsNone(idle.remaining(self.db, fast, 0))
        self.assertEqual(idle.remaining(self.db, slow, 0), 0)

    def test_sessions_and_turns_do_not_reset_each_other(self):
        keys = [self.complete(session=session, turn=turn)
                for session, turn in (("one", "root"), ("one", "worker"), ("two", "root"))]
        idle.update(self.db, event("Stop", session="one", turn="root"))
        self.assertIsNone(idle.remaining(self.db, keys[0], 0))
        self.assertEqual(idle.remaining(self.db, keys[1], 0), 0)
        self.assertEqual(idle.remaining(self.db, keys[2], 0), 0)

    def test_stop_interrupt_reset_and_session_end_cancel_delayed_posts(self):
        for kind in ("Stop", "Interrupt", "SessionEnd", "PreToolUse"):
            with self.subTest(kind=kind):
                key = self.complete()
                idle.update(self.db, event("PreToolUse", call="delayed"))
                cancel = event(kind, tool="mcp__node_repl__js_reset")
                if kind == "SessionEnd":
                    cancel.pop("turn_id")
                idle.update(self.db, cancel)
                self.assertIsNone(idle.remaining(self.db, key, 0))
                self.assertIsNone(idle.update(self.db, event("PostToolUse", call="delayed")))

    def test_session_end_preserves_other_sessions(self):
        key = self.complete(session="other")
        self.complete()
        idle.update(self.db, event("SessionEnd"))
        self.assertEqual(idle.remaining(self.db, key, 0), 0)

    def test_atomic_reminder_claim_across_process_connections(self):
        key = self.complete()

        def claim(_):
            db = idle.connect(self.path)
            try:
                return idle.remaining(db, key, 0)
            finally:
                db.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(claim, range(8)))
        self.assertEqual(results.count(0), 1)
        self.assertEqual(results.count(None), 7)

    def test_waiting_timer_cancels_and_fresh_activity_rearms(self):
        idle.run(event("PreToolUse"), self.path)
        with patch.object(idle.time, "sleep", side_effect=lambda _: idle.run(event("Stop"), self.path)):
            self.assertIsNone(idle.run(event("PostToolUse"), self.path))
        self.assertIn(idle.GUIDE, idle.run(event("PreToolUse"), self.path))
        self.assertIn("idle", idle.run(event("PostToolUse"), self.path, idle_seconds=0))

    def test_expired_records_are_pruned_without_affecting_live_records(self):
        with patch.object(idle.time, "time", return_value=10):
            idle.update(self.db, event("PreToolUse", session="old"))
        with patch.object(idle.time, "time", return_value=86411):
            idle.update(self.db, event("PreToolUse"))
        self.assertEqual(self.db.execute("SELECT session FROM calls").fetchall(), [("session-a",)])

    def test_state_is_private_and_symlinks_or_public_paths_are_refused(self):
        self.assertEqual(self.path.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.path.parent.chmod(0o755)
        with self.assertRaises(ValueError):
            idle.connect(self.path)
        self.path.parent.chmod(0o700)
        link = self.path.with_name("link.sqlite3")
        link.symlink_to(self.path)
        with self.assertRaises(OSError):
            idle.connect(link)

    def test_invalid_identity_cannot_cancel_a_live_turn(self):
        key = self.complete()
        for bad in ("", None, 3, [], "x\0y", "x" * 513):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                idle.update(self.db, event("Stop", turn=bad))
        self.assertEqual(idle.remaining(self.db, key, 0), 0)

    def test_unrelated_tools_and_missing_cleanup_state_create_nothing(self):
        missing = self.path.parent / "unused/idle.sqlite3"
        self.assertIsNone(idle.run(event("PreToolUse", tool="Bash"), missing))
        self.assertIsNone(idle.run(event("Stop"), missing))
        self.assertFalse(missing.parent.exists())

    def test_protocol_is_informational_and_excludes_inputs_and_outputs(self):
        payload = {**event("PreToolUse"), "tool_input": {"private": "never persist"},
                   "tool_response": "never persist"}
        result = subprocess.run([sys.executable, "-B", str(script)], input=json.dumps(payload),
                                text=True, capture_output=True,
                                env={**os.environ, "XDG_STATE_HOME": self.temp.name}, check=True)
        output = json.loads(result.stdout)
        self.assertEqual(set(output), {"hookSpecificOutput"})
        self.assertEqual(output["hookSpecificOutput"]["hookEventName"], "PreToolUse")
        self.assertNotIn("never persist", result.stdout)
        state = Path(self.temp.name) / "chatgpt-browser/idle.sqlite3"
        self.assertNotIn(b"never persist", state.read_bytes())

    def test_real_background_process_emits_once_and_cancels_when_activity_resumes(self):
        env = {**os.environ, "XDG_STATE_HOME": self.temp.name}
        bootstrap = (
            "import functools, importlib.util, sys; "
            "spec=importlib.util.spec_from_file_location('idle',sys.argv[1]); "
            "idle=importlib.util.module_from_spec(spec); spec.loader.exec_module(idle); "
            "idle.run=functools.partial(idle.run,idle_seconds=0.3); "
            "sleep=idle.time.sleep; "
            "idle.time.sleep=lambda seconds: (print('waiting',file=sys.stderr,flush=True),sleep(seconds))[-1]; "
            "idle.main()"
        )

        def mark(call):
            subprocess.run([sys.executable, "-B", str(script)],
                           input=json.dumps(event("PreToolUse", call=call)), env=env,
                           text=True, capture_output=True, check=True)

        for cancel in (False, True):
            call = str(cancel)
            mark(call)
            start = time.monotonic()
            process = subprocess.Popen([sys.executable, "-B", "-c", bootstrap, str(script)],
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, text=True, env=env)
            self.addCleanup(lambda p=process: p.kill() if p.poll() is None else None)
            process.stdin.write(json.dumps(event("PostToolUse", call=call)))
            process.stdin.close()
            process.stdin = None
            ready, _, _ = select.select([process.stderr], [], [], 5)
            self.assertTrue(ready, "Timer never reached its background wait")
            self.assertEqual(process.stderr.readline().strip(), "waiting")
            if cancel:
                mark("new-activity")  # another process resets the timer while this one waits
            output, errors = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 0, errors)
            if cancel:
                self.assertEqual(output, "")
            else:
                self.assertGreaterEqual(time.monotonic() - start, 0.3)
                self.assertEqual(set(json.loads(output)), {"hookSpecificOutput"})

    def test_malformed_protocol_is_advisory_and_invalid_xdg_uses_home(self):
        with patch.object(idle.sys, "stdin", io.StringIO("[]")), \
                patch.object(idle.sys, "stderr", io.StringIO()) as errors:
            idle.main()
        self.assertIn("unavailable", errors.getvalue())
        for value in ("", ".", "relative"):
            with patch.dict(os.environ, {"XDG_STATE_HOME": value}):
                self.assertEqual(idle.state_path(), Path.home() / ".local/state/chatgpt-browser/idle.sqlite3")


if __name__ == "__main__":
    unittest.main()

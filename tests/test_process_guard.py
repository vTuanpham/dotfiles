"""Parse commands inertly; the procps smoke test signals only its own disposable child."""

import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "shell/.local/libexec/agent-process-guard.py"
spec = importlib.util.spec_from_file_location("process_guard", SCRIPT)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


@unittest.skipUnless(shutil.which("shfmt"), "install shfmt to verify shell matching")
class ProcessGuardTests(unittest.TestCase):
    def test_blocks_actual_full_command_matches_across_shell_constructs(self):
        commands = [
            'pkill -f "worker"; printf cleanup',
            'pgrep -af worker',
            'pkill -TERM --full worker',
            'pkill -ALRM -f worker',
            'pkill --signal=ALRM -f worker',
            'pgrep -F -A -f worker',
            'pgrep -p -A -f worker',
            'pgrep -uA -f worker',
            'true && pkill -if worker || printf done',
            'until pgrep -f worker; do sleep 1; done',
            'printf "%s" "$(pgrep -f worker)"',
            'cat <(pgrep -f worker)',
            'env MODE=test rtk summary bash -lc \'pkill -f worker\'',
            'rtk err sudo -u nobody /usr/bin/pkill -f worker',
            'rtk run pkill -f worker',
            'rtk --skip-env run -- pkill -f worker',
            'rtk run --shell bash -c "pkill -f worker"',
            'rtk run --command="pgrep -af worker"',
            'timeout -k 1 5 pkill -f worker',
            'docker exec container pgrep -f worker',
            'docker exec -u nobody container sh -lc "pkill -f worker"',
            'podman exec container pgrep -af worker',
            'python app.py | pkill -f worker',
        ]
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual(guard.inspect(command), guard.REASON)

    def test_allows_data_examples_and_precise_process_operations(self):
        commands = [
            'printf "%s\\n" "pkill -f worker"',
            'printf "%s\\n" "example; pkill -f worker"',
            "rg 'pkill -f|pgrep -f' transcript.jsonl",
            "cat <<'EOF'\npkill -f worker\nEOF\n",
            'kill -TERM "$owned_pid"',
            'pgrep -x worker',
            'pkill -x worker',
            'pgrep --help',
            'pgrep -- --full',
            'pgrep --ignore-ancestors --full worker',
            'pkill -Af worker',
            'rtk run printf "%s" "pkill -f worker"',
            'rtk run -c \'printf "%s" "pkill -f worker"\'',
            'docker exec container printf "%s" "pkill -f worker"',
        ]
        for command in commands:
            with self.subTest(command=command):
                self.assertIsNone(guard.inspect(command))

    def test_only_parses_the_tool_input_and_returns_a_native_denial(self):
        for field in ("command", "cmd"):
            event = {"tool_name": "Bash", "tool_input": {field: 'pkill -f "test-only-not-executed"'}}
            result = subprocess.run([sys.executable, "-I", str(SCRIPT)], input=json.dumps(event),
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, "")
            self.assertIn("owned PID", result.stderr)

    def test_unrelated_calls_and_malformed_events_have_no_side_effects(self):
        for event in ({}, {"tool_input": {"command": "git status"}}, {"tool_input": None}):
            result = subprocess.run([sys.executable, "-I", str(SCRIPT)], input=json.dumps(event),
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout + result.stderr, "")

    def test_antigravity_uses_native_json_decisions_without_approving_permissions(self):
        for command, decision in (("pkill -f worker", "deny"), ("pgrep -Af worker", "allow"),
                                  ("git status", "allow")):
            event = {"toolCall": {"name": "run_command", "args": {"CommandLine": command}}}
            result = subprocess.run([sys.executable, "-I", str(SCRIPT)], input=json.dumps(event),
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, "")
            response = json.loads(result.stdout)
            self.assertEqual(response["decision"], decision)
            if decision == "deny":
                self.assertIn("owned PID", response["reason"])

    def test_parser_failure_and_unknown_ast_do_not_silently_allow_candidates(self):
        with patch.object(guard.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "", "")):
            self.assertIn("could not parse", guard.inspect("pkill -f worker"))
        with patch.object(guard.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "{}", "")):
            with self.assertRaises(ValueError):
                guard.inspect("pkill -f worker")

    def test_ancestor_exclusion_keeps_its_shell_alive_and_stops_only_fixture_child(self):
        directory = os.environ.get("PROCESS_TEST_BIN_DIR")
        pgrep = str(Path(directory) / "pgrep") if directory else shutil.which("pgrep")
        pkill = str(Path(directory) / "pkill") if directory else shutil.which("pkill")
        help_text = subprocess.run([pgrep, "--help"], capture_output=True, text=True, timeout=5)
        if "--ignore-ancestors" not in help_text.stdout:
            self.skipTest("modern procps needed for ancestor-exclusion smoke test")
        marker = "process-guard-fixture-" + uuid.uuid4().hex
        script = '''
exec -a "$1" sleep 30 & child=$!
trap 'if [ -n "$child" ]; then kill "$child" 2>/dev/null || :; fi' EXIT
printf 'parent:%s child:%s\\n' "$$" "$child"
printf 'before\\n'; "$2" -f -- "$1"
printf 'protected\\n'; "$2" -A -f -- "$1"
printf 'killing\\n'; "$3" -A -f -- "$1"; killed=$?
wait "$child"; stopped=$?; child=
printf 'survived:%s stopped:%s\\n' "$killed" "$stopped"
'''
        process = subprocess.Popen(["bash", "-c", script, "fixture", marker, pgrep, pkill],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                   start_new_session=True)
        try:
            output, error = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 0, error)
            lines = output.splitlines()
            parent, child = (int(word.split(":")[1]) for word in lines[0].split())
            before = lines[lines.index("before") + 1:lines.index("protected")]
            protected = lines[lines.index("protected") + 1:lines.index("killing")]
            self.assertIn(str(parent), before)
            self.assertIn(str(child), before)
            self.assertEqual(protected, [str(child)])
            self.assertEqual(lines[-1], "survived:0 stopped:143")
        finally:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()

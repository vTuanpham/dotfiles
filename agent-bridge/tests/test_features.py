import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent_bridge import agy, cli, codex
from agent_bridge.core import MESSAGING_RULE, human, tree_size, worker_env


def event(path, kind, **fields):
    with (path / "live.jsonl").open("a") as stream:
        stream.write(json.dumps({"kind": kind, **fields}) + "\n")


def test_linger_auto_answers_urgent_and_keeps_runner_until_resume(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_BRIDGE_ROOT_WAIT", "0")
    state_path = tmp_path / "state.json"
    (tmp_path / "steer").mkdir()
    state = {"autoAnswers": 0}
    state_path.write_text(json.dumps(state))
    calls = []

    class Backend:
        def run(self, job, state, path, prompt, resume=False):
            calls.append((prompt, resume, json.loads(path.read_text()).get("runnerPid")))
            if not resume:
                event(job, "message", level="urgent", text="Need a choice")
                event(job, "turn_completed")
            else:
                event(job, "steer_sent")
                event(job, "turn_completed")

    cli.run_with_linger(tmp_path, state, state_path, Backend(), "start", False, {})
    assert calls == [("start", False, None), ("", True, cli.os.getpid())]
    assert json.loads(state_path.read_text()).get("runnerPid") is None
    assert json.loads(state_path.read_text())["autoAnswers"] == 1
    assert "root_absent" in (tmp_path / "live.jsonl").read_text()


def test_linger_does_not_restart_after_stop(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_BRIDGE_ROOT_WAIT", "0")
    state_path = tmp_path / "state.json"
    state_path.write_text("{}")
    (tmp_path / "steer").mkdir()
    calls = []

    class Backend:
        def run(self, job, state, path, prompt, resume=False):
            calls.append(prompt)
            event(job, "message", level="urgent", text="Need a choice")
            event(job, "stopped")

    cli.run_with_linger(tmp_path, {}, state_path, Backend(), "start", False, {})
    assert calls == ["start"]


def test_worker_env_and_peer_discovery_rule():
    current = Path("/jobs/owner/one")
    assert worker_env(current)["AGENT_BRIDGE_JOB"] == "owner/one"
    assert "agent-bridge peers lists your sibling workers" in MESSAGING_RULE


def test_worker_peers_are_limited_to_current_owner(monkeypatch, tmp_path, capsys):
    jobs = tmp_path / "jobs"
    current, sibling, other = (
        jobs / "owner" / "current",
        jobs / "owner" / "sibling",
        jobs / "other" / "hidden",
    )
    current.mkdir(parents=True)
    sibling.mkdir()
    other.mkdir(parents=True)
    for path, backend in ((sibling, "agy"), (other, "codex")):
        (path / "state.json").write_text(json.dumps({"backend": backend, "model": "m", "title": path.name}))
    monkeypatch.setattr("agent_bridge.core.JOBS", jobs)
    monkeypatch.setenv("AGENT_BRIDGE_WORKER", "1")
    monkeypatch.setenv("AGENT_BRIDGE_JOB", "owner/current")
    monkeypatch.setattr(sys, "argv", ["agent-bridge", "peers"])
    monkeypatch.setattr("agent_bridge.watch.running", lambda _: False)
    cli.main()
    output = capsys.readouterr().out
    assert "sibling\tagy\tm\tsibling\tidle" in output
    assert "hidden" not in output


def test_harness_detection_uses_documented_markers(monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    assert cli.harness() == "claude"
    monkeypatch.delenv("CLAUDECODE")
    monkeypatch.setenv("CODEX_THREAD_ID", "thread")
    assert cli.harness() == "codex"
    monkeypatch.delenv("CODEX_THREAD_ID")
    assert cli.harness() == "unknown"


def test_owners_summarizes_root_activity_and_unanswered_questions(monkeypatch, tmp_path, capsys):
    jobs = tmp_path / "jobs"
    job = jobs / "owner" / "question"
    job.mkdir(parents=True)
    (job / "state.json").write_text(json.dumps({"runnerPid": None, "backend": "codex"}))
    event(job, "question", level="urgent")
    owner = job.parent
    cli.record_root(job)
    monkeypatch.setattr(cli, "JOBS", jobs)
    monkeypatch.setattr("agent_bridge.core.JOBS", jobs)
    monkeypatch.setattr("agent_bridge.watch.JOBS", jobs)
    monkeypatch.setattr(sys, "argv", ["agent-bridge", "owners"])
    monkeypatch.setattr("agent_bridge.watch.running", lambda _: False)
    cli.main()
    (job / "home").mkdir()
    (job / "home/real").symlink_to(tmp_path)  # a link to a big tree must not be counted
    (job / "out.bin").write_bytes(b"x" * 3000)
    cli.main()
    assert "jobs=1 running=0 unanswered_urgent=1 size=" in capsys.readouterr().out.splitlines()[-1]
    assert tree_size(job) < 10_000 and human(3000) == "2.9K"
    assert set(json.loads((owner / "root.json").read_text())) == {"at", "harness"}
    (job / "steer").mkdir()
    (job / "steer/001.md").write_text("answer")
    assert cli.unanswered_urgent(job) == 0


def test_result_joins_messages_from_last_turn_only(tmp_path):
    event(tmp_path, "message", text="old")
    event(tmp_path, "turn_completed")
    event(tmp_path, "message", text="part one")
    event(tmp_path, "message", text="part two")
    event(tmp_path, "turn_completed")
    assert cli.result_text(tmp_path) == "part one\n\npart two"
    assert cli.result_text(tmp_path, all_messages=True) == "old\n\npart one\n\npart two"
    event(tmp_path, "message", text="partial final turn")
    assert cli.result_text(tmp_path) == "partial final turn"


def test_help_is_compact_command_map(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["agent-bridge", "--help"])
    with pytest.raises(SystemExit) as done:
        cli.main()
    assert done.value.code == 0
    output = capsys.readouterr().out
    assert len(output.encode()) < 3000
    for command in ("start", "resume", "steer", "watch", "result", "retire", "restore", "purge",
                    "compact", "guide", "sessions",
                    "owners", "peers", "interrupt", "stop", "models", "quota", "stale", "refresh"):
        assert f"    {command} " in output
    assert "start ... --watch" in output and "resumes idle jobs" in output
    assert "guide workflow" in output and "guide plans" in output


@pytest.mark.parametrize("topic, names", [(None, ("overview", "models")),
                                        ("workflow", ("overview",)), ("plans", ("models",))])
def test_long_guidance_remains_reachable(monkeypatch, capsys, topic, names):
    monkeypatch.setattr(sys, "argv", ["agent-bridge", "guide", *([topic] if topic else [])])
    cli.main()
    assert capsys.readouterr().out == cli.guide(*names) + "\n"


@pytest.mark.parametrize("argv, hint", [
    (["status", "owner/job"], "use watch <job>, result <job>, or owners"),
    (["backends"], "use models --backend"),
    (["steer", "owner/job", "--message", "follow up"], "positional argument"),
    (["steer", "owner/job", "--message=follow up"], "positional argument"),
])
def test_guessed_commands_fail_with_hints(monkeypatch, capsys, argv, hint):
    monkeypatch.delenv("AGENT_BRIDGE_WORKER", raising=False)
    monkeypatch.setattr(sys, "argv", ["agent-bridge", *argv])
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2
    assert hint in capsys.readouterr().err


def test_queue_only_and_resume_queue_count(monkeypatch, tmp_path, capsys):
    job = tmp_path / "owner/job"
    job.mkdir(parents=True)
    state = {"backend": "codex", "activeTurnId": None}
    (job / "state.json").write_text(json.dumps(state))
    monkeypatch.delenv("AGENT_BRIDGE_WORKER", raising=False)
    monkeypatch.setattr(cli, "resolve_job", lambda _: job)
    monkeypatch.setattr(cli.os, "fork", lambda: pytest.fail("--queue must not start a runner"))
    monkeypatch.setattr(sys, "argv", ["agent-bridge", "steer", "owner/job", "follow up", "--queue"])
    cli.main()
    output = capsys.readouterr().out
    assert "queued:" in output and "agent-bridge resume owner/job" in output
    assert (job / "steer/001.md").read_text().strip() == "follow up"
    (job / "steer/002.md").write_text("another follow up")
    (job / "steer/sent").mkdir()
    (job / "steer/sent/000.md").write_text("already sent")
    delivered = []

    def run(job, state, path, prompt, resume=False):
        from agent_bridge.core import poll_steers

        assert resume and prompt == ""
        while poll_steers(job, lambda text, cid: delivered.append(text), state=state):
            pass

    monkeypatch.setattr(codex, "run", run)
    monkeypatch.setattr(cli, "linger", lambda *args: None)
    monkeypatch.setattr(sys, "argv", ["agent-bridge", "resume", "owner/job"])
    cli.main()
    assert "resume: delivering 2 queued steer(s)" in capsys.readouterr().out
    assert delivered == ["follow up", "another follow up"]


@pytest.mark.parametrize("backend", ["codex", "claude", "agy", "opencode"])
def test_compact_cli_routes_only_supported_backends(monkeypatch, tmp_path, capsys, backend):
    job = tmp_path / "owner/job"
    job.mkdir(parents=True)
    (job / "state.json").write_text(json.dumps({"backend": backend}))
    monkeypatch.delenv("AGENT_BRIDGE_WORKER", raising=False)
    monkeypatch.setattr(cli, "resolve_job", lambda _: job)
    monkeypatch.setattr(sys, "argv", ["agent-bridge", "compact", "owner/job"])
    calls = []
    monkeypatch.setattr(cli.BACKENDS[backend], "run", lambda *a, **kw: calls.append(kw))
    monkeypatch.setattr(cli, "linger", lambda *a: pytest.fail("compaction must not resume queued steers"))
    if backend in ("codex", "claude"):
        cli.main()
        assert calls == [{"resume": True, "compact": True}]
    else:
        with pytest.raises(SystemExit) as error:
            cli.main()
        assert error.value.code == 1
        assert "compact is supported only by codex and claude" in capsys.readouterr().err
        assert not calls


def test_retire_archives_report_and_keeps_job(tmp_path, monkeypatch, capsys):
    jobs = tmp_path / "jobs"
    job = jobs / "owner" / "done"
    job.mkdir(parents=True)
    (job / "state.json").write_text(json.dumps({"backend": "codex", "model": "m", "title": "Done"}))
    (job / "prompt.md").write_text("prompt body")
    event(job, "message", text="Final report")
    archive = tmp_path / "archive.jsonl"
    monkeypatch.setattr("agent_bridge.core.JOBS", jobs)
    monkeypatch.setattr(cli, "ARCHIVE", archive)
    monkeypatch.delenv("AGENT_BRIDGE_WORKER", raising=False)
    monkeypatch.setattr(sys, "argv", ["agent-bridge", "retire", "owner/done"])
    monkeypatch.setattr("agent_bridge.watch.running", lambda _: True)
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 1 and job.exists() and not archive.exists()
    monkeypatch.setattr("agent_bridge.watch.running", lambda _: False)
    cli.main()
    assert "retired owner/done; purge after " in capsys.readouterr().out
    row = json.loads(archive.read_text())
    assert row["job"] == "owner/done" and row["prompt"] == "prompt body"
    assert row["final"] == "Final report"
    assert job.exists()
    state = json.loads((job / "state.json").read_text())
    assert state["retiredAt"] == row["retiredAt"]
    assert state["purgeAfter"] == row["purgeAfter"]


def test_agy_fallback_uses_fresh_account_quota_and_resumes(monkeypatch, tmp_path):
    accounts = tmp_path / "accounts"
    for account in ("a1", "a2"):
        directory = accounts / account
        (directory / agy.TOKEN).parent.mkdir(parents=True)
        (directory / agy.TOKEN).write_text("token")
        (directory / "quota.json").write_text(
            json.dumps(
                {
                    "at": "2026-10-20T00:00:00+00:00",
                    "rows": [{"group": "gemini", "remaining": 50, "resets": "2026-10-21T00:00:00+00:00"}],
                }
            )
        )
    monkeypatch.setattr(agy, "ACCOUNTS", accounts)
    monkeypatch.setattr(agy, "switch_account", lambda job, state, account: state.update(account=account))
    now = datetime.now(timezone.utc).isoformat()
    for account in ("a1", "a2"):
        directory = accounts / account
        (directory / "quota.json").write_text(
            json.dumps(
                {
                    "at": now,
                    "rows": [{"group": "gemini", "remaining": 50, "resets": "2026-10-21T00:00:00+00:00"}],
                }
            )
        )
    job = tmp_path / "owner" / "job"
    job.mkdir(parents=True)
    state = {"account": "a1", "model": "gemini-pro"}
    path = job / "state.json"
    path.write_text(json.dumps(state))
    event(job, "turn_completed", error="quota reached")
    resumed = []

    def run(job, state, path, prompt, resume=False):
        resumed.append((state["account"], prompt, resume))
        event(job, "turn_completed", error=None)

    monkeypatch.setattr(agy, "run", run)
    agy.fallback(job, state, path)
    assert resumed == [("a2", "Continue where you left off.", True)]
    assert any(
        json.loads(line)["kind"] == "account_switched"
        for line in (job / "live.jsonl").read_text().splitlines()
    )

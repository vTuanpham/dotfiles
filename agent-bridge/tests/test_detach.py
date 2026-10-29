import json
import sys
from contextlib import nullcontext
from pathlib import Path

import pytest

from agent_bridge import cli, core


def args(monkeypatch, job):
    monkeypatch.delenv("AGENT_BRIDGE_WORKER", raising=False)
    job.mkdir(parents=True)
    (job / "prompt.md").write_text("work")
    monkeypatch.setattr(cli, "resolve_job", lambda _: job)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agent-bridge",
            "start",
            "owner/job",
            "--backend",
            "claude",
            "--title",
            "Useful title",
            "--cwd",
            str(job),
            "--sandbox",
            "read-only",
            "--detach",
        ],
    )
    monkeypatch.setattr(sys, "stdin", type("Input", (), {"isatty": lambda self: True})())


def test_detach_runner_pid_handshake(monkeypatch, tmp_path, capsys):
    job = tmp_path / "job"
    args(monkeypatch, job)

    def spawn():
        state_path = job / "state.json"
        state = json.loads(state_path.read_text())
        state["runnerPid"] = cli.os.getpid()
        state_path.write_text(json.dumps(state))
        return cli.os.getpid()

    monkeypatch.setattr(cli.os, "fork", spawn)
    cli.main()
    assert capsys.readouterr().out.strip() == str(job)


@pytest.mark.parametrize("quiet, code", [(True, None), (False, 124)])
def test_watch_flag_follows_the_detached_job_from_before_launch(monkeypatch, tmp_path, capsys, quiet, code):
    job = tmp_path / "job"
    args(monkeypatch, job)
    (job / "live.jsonl").write_text("old\n")
    monkeypatch.setattr(sys, "argv", [*sys.argv, "--watch"])
    seen = {}

    def spawn():
        state_path = job / "state.json"
        state = json.loads(state_path.read_text())
        state["runnerPid"] = cli.os.getpid()
        state_path.write_text(json.dumps(state))
        return cli.os.getpid()

    def fake_watch(owned, until_event, **kwargs):
        seen.update(owned=owned, until_event=until_event, **kwargs)
        return quiet

    monkeypatch.setattr(cli.os, "fork", spawn)
    monkeypatch.setattr(cli, "watch", fake_watch)
    if code:
        with pytest.raises(SystemExit) as stop:
            cli.main()
        assert stop.value.code == code
    else:
        cli.main()
    assert capsys.readouterr().out.strip() == str(job)
    assert seen == {
        "owned": [f"{job.parent.name}/job"],
        "until_event": True,
        "timeout": 1800,
        "offsets": {job: len("old\n")},  # the old event is not replayed
    }


def test_detach_handshake_timeout_reports_runner_log(monkeypatch, tmp_path, capsys):
    job = tmp_path / "job"
    args(monkeypatch, job)
    (job / "runner.log").write_text("backend failed")

    def stale_runner_pid():
        state_path = job / "state.json"
        state = json.loads(state_path.read_text())
        state["runnerPid"] = cli.os.getpid()  # an existing process, but not the forked runner
        state_path.write_text(json.dumps(state))
        return 123

    monkeypatch.setattr(cli.os, "fork", stale_runner_pid)
    times = iter([0, 11])
    monkeypatch.setattr(cli.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(cli.time, "sleep", lambda _: None)
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 1
    output = capsys.readouterr().err
    assert "runner.log tail" in output
    assert "backend failed" in output


def test_detach_handshake_fails_fast_when_child_exits(monkeypatch, tmp_path, capsys):
    job = tmp_path / "job"
    args(monkeypatch, job)
    monkeypatch.setattr(cli.os, "fork", lambda: 123)
    monkeypatch.setattr(cli.os, "waitpid", lambda pid, flags: (pid, 256))
    monkeypatch.setattr(cli.time, "monotonic", lambda: 0)
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 1
    assert "exited before startup" in capsys.readouterr().err


def test_detached_prestart_failure_is_logged(monkeypatch, tmp_path):
    job = tmp_path / "job"
    args(monkeypatch, job)
    # This test replaces process-wide os.open for detached stdio, not state-lock behavior.
    monkeypatch.setattr(core, "state_lock", lambda _: nullcontext())
    monkeypatch.setattr(cli, "lock_runner", lambda _: 55)
    monkeypatch.setattr(cli.os, "fork", lambda: 0)
    monkeypatch.setattr(cli.os, "setsid", lambda: None)
    real_open = cli.os.open

    def open_detached_stdio(path, *args, **kwargs):
        if Path(path).name == "root.lock":
            return real_open(path, *args, **kwargs)
        return 56

    monkeypatch.setattr(cli.os, "open", open_detached_stdio)
    monkeypatch.setattr(cli.os, "dup2", lambda *args: None)
    real_close = cli.os.close
    monkeypatch.setattr(cli.os, "close", lambda fd: None if fd in {55, 56} else real_close(fd))
    monkeypatch.setattr(cli.os, "_exit", lambda code: (_ for _ in ()).throw(SystemExit(code)))
    monkeypatch.setattr(
        cli.claude, "run", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("prestart"))
    )
    with pytest.raises(SystemExit):
        cli.main()
    event = json.loads((job / "live.jsonl").read_text().splitlines()[0])
    assert event["kind"] == "error" and event["message"] == "prestart"


def test_worker_cannot_drive_jobs(monkeypatch, capsys):
    monkeypatch.setenv("AGENT_BRIDGE_WORKER", "1")
    monkeypatch.setattr(sys, "argv", ["agent-bridge", "resume", "owner/job"])
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2
    assert "delegated workers can't drive agent-bridge jobs" in capsys.readouterr().err


@pytest.mark.parametrize("backend", ["codex", "claude"])
def test_compact_refuses_active_turn(monkeypatch, tmp_path, capsys, backend):
    monkeypatch.delenv("AGENT_BRIDGE_WORKER", raising=False)
    job = tmp_path / "job"
    job.mkdir()
    (job / "state.json").write_text(json.dumps({"backend": backend, "activeTurnId": "turn-1"}))
    monkeypatch.setattr(cli, "resolve_job", lambda _: job)
    monkeypatch.setattr(sys, "argv", ["agent-bridge", "compact", "owner/job"])
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 1
    assert "active turn" in capsys.readouterr().err


def test_codex_start_records_active_account_number(monkeypatch, tmp_path):
    job = tmp_path / "job"
    job.mkdir()
    (job / "prompt.md").write_text("work")
    monkeypatch.delenv("AGENT_BRIDGE_WORKER", raising=False)
    monkeypatch.setattr(cli, "resolve_job", lambda _: job)
    monkeypatch.setattr(cli.codex, "active_account", lambda: "3")
    monkeypatch.setattr(cli.codex, "run", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agent-bridge",
            "start",
            "owner/job",
            "--backend",
            "codex",
            "--title",
            "Fix Codex auth",
            "--cwd",
            str(job),
            "--sandbox",
            "read-only",
        ],
    )
    cli.main()
    state = json.loads((job / "state.json").read_text())
    assert state["account"] == "3"
    assert state["title"] == "Fix Codex auth"


def test_resume_switches_agy_account_and_rejects_other_backends(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("AGENT_BRIDGE_WORKER", raising=False)
    job = tmp_path / "job"
    home = job / "home"
    home.mkdir(parents=True)
    (job / "state.json").write_text(json.dumps({"backend": "agy", "account": "a1"}))
    (job / "prompt.md").write_text("continue")
    accounts = tmp_path / "accounts"
    token = accounts / "a2" / cli.agy.TOKEN
    token.parent.mkdir(parents=True)
    token.write_text("token")
    old_token = accounts / "a1" / cli.agy.TOKEN
    old_token.parent.mkdir(parents=True)
    old_token.write_text("old")
    (home / cli.agy.TOKEN).parent.mkdir(parents=True)
    (home / cli.agy.TOKEN).symlink_to(old_token)
    monkeypatch.setattr(cli.agy, "ACCOUNTS", accounts)
    monkeypatch.setattr(cli, "resolve_job", lambda _: job)
    monkeypatch.setattr(cli.agy, "run", lambda *args, **kwargs: None)
    monkeypatch.setattr(sys, "argv", ["agent-bridge", "resume", "owner/job", "--account", "a2"])

    cli.main()

    state = json.loads((job / "state.json").read_text())
    assert state["account"] == "a2"
    assert (home / cli.agy.TOKEN).resolve() == token

    state["backend"] = "codex"
    (job / "state.json").write_text(json.dumps(state))
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 1
    assert "only for agy resumes" in capsys.readouterr().err


def test_start_rejects_invalid_human_titles(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("AGENT_BRIDGE_WORKER", raising=False)
    job = tmp_path / "job"
    job.mkdir()
    (job / "prompt.md").write_text("work")
    monkeypatch.setattr(cli, "resolve_job", lambda _: job)
    for title in ("ab", "codex", "   ", "first\nsecond", "x" * 49):
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "agent-bridge",
                "start",
                "owner/job",
                "--backend",
                "codex",
                "--title",
                title,
                "--cwd",
                str(job),
                "--sandbox",
                "read-only",
            ],
        )
        with pytest.raises(SystemExit) as error:
            cli.main()
        assert error.value.code == 1
        assert "--title must" in capsys.readouterr().err

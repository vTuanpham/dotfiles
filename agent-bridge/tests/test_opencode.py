import json
from collections import deque
from pathlib import Path

import pytest

from agent_bridge import opencode


def state(tmp_path, sandbox="workspace-write"):
    return {
        "cwd": str(tmp_path),
        "title": "Probe task",
        "model": "openrouter/google/gemma-4-31b-it:free",
        "effort": "high",
        "sessionId": "sid",
        "sandbox": sandbox,
        "writableRoots": [str(tmp_path)],
    }


def test_command_confines_both_modes_and_sets_permissions(monkeypatch, tmp_path):
    st = state(tmp_path)
    job = tmp_path / "job"
    home = tmp_path / "home"
    shared_auth = home / ".local/share/opencode/auth.json"
    shared_cache = home / ".cache/opencode"
    shared_auth.parent.mkdir(parents=True)
    shared_auth.write_text('{"key":"secret"}')
    (shared_cache / "bin").mkdir(parents=True)
    for name in ("node_modules", "packages"):
        (shared_cache / name).mkdir()
    (shared_cache / "package.json").write_text("{}")
    (shared_cache / "models.json").write_text("{}")
    monkeypatch.setattr(opencode.Path, "home", lambda: home)
    for key in ("OPENCODE_CONFIG", "OPENCODE_CONFIG_DIR", "OPENCODE_SERVER_PASSWORD", "OPENCODE_PASSWORD"):
        monkeypatch.setenv(key, "inherited")
    cmd, env = opencode.command(st, job, "prompt", resume=True)
    assert cmd[0] == "bwrap" and "--ro-bind" in cmd and "--dev" in cmd and "--proc" in cmd
    assert "--bind" in cmd and str(tmp_path) in cmd
    assert "--die-with-parent" in cmd
    assert all(str(job) != cmd[index + 1] for index, value in enumerate(cmd) if value == "--bind")
    bind_sources = [cmd[index + 1] for index, value in enumerate(cmd) if value == "--bind"]
    private = job / "home"
    assert bind_sources == [str(private), str(tmp_path), str(opencode.heavy_directory())]
    out = job / "out"  # a writable root inside the job dir must be mounted after the read-only job root
    cmd_out, _ = opencode.command({**st, "writableRoots": [str(out)]}, job, "prompt", resume=True)
    assert cmd_out.index(str(out)) > cmd_out.index(str(job))
    assert private.stat().st_mode & 0o777 == 0o700
    assert env["XDG_DATA_HOME"] == str(private / "data")
    assert env["XDG_STATE_HOME"] == str(private / "state")
    assert env["XDG_CACHE_HOME"] == str(private / "cache")
    assert (private / "data/opencode/auth.json").read_text() == '{"key":"secret"}'
    assert (private / "data/opencode/auth.json").stat().st_mode & 0o777 == 0o600
    assert (private / "cache/opencode/models.json").read_text() == "{}"
    ro_binds = [(cmd[index + 1], cmd[index + 2]) for index, value in enumerate(cmd) if value == "--ro-bind"]
    assert (str(job), str(job)) in ro_binds
    cache_binds = [(source, target) for source, target in ro_binds if Path(source).parent == shared_cache]
    assert {Path(target).name for _, target in cache_binds} == {
        "bin",
        "node_modules",
        "packages",
        "package.json",
    }
    assert len(cache_binds) == 4
    assert (home / ".config/opencode") not in [Path(source) for source in bind_sources]
    assert not any(
        key in env
        for key in ("OPENCODE_CONFIG", "OPENCODE_CONFIG_DIR", "OPENCODE_SERVER_PASSWORD", "OPENCODE_PASSWORD")
    )
    assert "--session" in cmd and "sid" in cmd
    assert "prompt" not in cmd
    assert cmd[cmd.index("-m") + 1] == "openrouter/google/gemma-4-31b-it:free#high"
    outside = {"external_directory": {"*": "allow"}}
    assert json.loads(env["OPENCODE_CONFIG_CONTENT"])["permission"] == outside

    st["sandbox"] = "read-only"
    cmd, env = opencode.command(st, job, "read", resume=False)
    bind_sources = [cmd[index + 1] for index, value in enumerate(cmd) if value == "--bind"]
    assert str(tmp_path) not in bind_sources
    permission = json.loads(env["OPENCODE_CONFIG_CONTENT"])["permission"]
    assert permission == {
        **outside,
        "edit": "deny",
        "bash": "deny",
        "webfetch": "deny",
        "websearch": "deny",
    }


def test_opencode_steer_survives_spawn_failure_and_is_redelivered(monkeypatch, tmp_path):
    job = tmp_path / "job"
    job.mkdir()
    (job / "steer").mkdir()
    (job / "steer/001.md").write_text("handle this steer")
    state_path = job / "state.json"
    st = {**state(tmp_path), "cwd": str(tmp_path)}
    monkeypatch.setattr(opencode, "command", lambda *args, **kwargs: (["opencode"], {}))
    monkeypatch.setattr(opencode, "runner_started", lambda *_: None)
    monkeypatch.setattr(opencode, "runner_finished", lambda *_: None)
    monkeypatch.setattr(
        opencode.subprocess,
        "Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("spawn failed")),
    )
    with pytest.raises(OSError, match="spawn failed"):
        opencode.run(job, st, state_path, "")
    assert (job / "steer/001.md").is_file()
    assert json.loads(state_path.read_text())["inflight"] == {"id": "steer-001", "file": "001.md"}

    commands, prompts = fake_turns(monkeypatch, [STOP, b""], [0])
    opencode.run(job, st, state_path, "", resume=True)
    assert prompts == [
        b"(redelivered after a runner restart; skip it if you already handled it)\nhandle this steer"
    ]
    assert (job / "steer/sent/001.md").is_file()
    assert json.loads(state_path.read_text())["inflight"] is None


def test_fixture_events_map_messages_tool_commands_and_usage(tmp_path):
    st = state(tmp_path)
    fixture = Path(__file__).parent / "fixtures" / "opencode.ndjson"
    for line in fixture.read_text().splitlines():
        opencode.process(json.loads(line), st, tmp_path)
    events = [json.loads(line) for line in (tmp_path / "live.jsonl").read_text().splitlines()]
    assert [event["kind"] for event in events] == [
        "thread_started",
        "message",
        "command_start",
        "command_end",
        "step_finished",
    ]
    assert events[-1]["level"] == "info"
    assert events[-1]["usage"]["input"] == 12 and events[-1]["cost"] == 0


def test_urgent_peer_message_routes(tmp_path):
    job, peer = tmp_path / "owner" / "worker", tmp_path / "owner" / "wake"
    job.mkdir(parents=True)
    peer.mkdir()
    (peer / "state.json").write_text("{}")
    opencode.process({"type": "text", "part": {"text": "URGENT: TO wake: check"}}, {}, job)
    assert (peer / "steer" / "001.md").read_text() == "[from worker] check\n"


def test_command_end_output_is_capped(tmp_path):
    opencode.process(
        {"type": "tool_use", "part": {"tool": "shell", "state": {"output": "x" * 2500}}},
        {},
        tmp_path,
    )
    event = json.loads((tmp_path / "live.jsonl").read_text().splitlines()[-1])
    assert len(event["output"]) == 2000


def test_free_tier_runs_only_zero_retention_models(tmp_path):
    for model in ("opencode/big-pickle", "opencode/mimo-v2.6-flash-free", ""):
        with pytest.raises(RuntimeError, match="zero-retention"):
            opencode.command({**state(tmp_path), "model": model, "effort": ""}, tmp_path, "p")
    assert not opencode.logged_free("opencode/glm-5.3-flash-free")
    assert not opencode.logged_free("openrouter/google/gemma-4-31b-it:free")  # another provider's own terms
    assert not opencode.logged_free("opencode-go/glm-5.3")


def fake_turns(monkeypatch, outputs, codes):
    """Each opencode process reads the next chunks from outputs (b"" ends it) and exits with the next code."""
    outputs, codes = deque(outputs), deque(codes)
    procs, commands, prompts = [], [], []

    class Input:
        def write(self, value):
            prompts.append(value)

        def close(self):
            pass

    class Process:
        def __init__(self, *args, **kwargs):
            self.pid, self.returncode = 100 + len(procs), codes.popleft()
            self.stdout = type("Output", (), {"fileno": lambda self: 42 + len(procs)})()
            self.stdin = Input()
            procs.append(self)

        def wait(self, timeout=None):
            return self.returncode

        def poll(self):
            return self.returncode

    def popen(cmd, **kwargs):
        commands.append(cmd)
        return Process()

    monkeypatch.setattr(opencode, "capped", lambda cmd, state=None: cmd)
    monkeypatch.setattr(opencode.subprocess, "Popen", popen)
    monkeypatch.setattr(opencode.select, "select", lambda *_: ([procs[-1].stdout], [], []))
    monkeypatch.setattr(opencode.os, "read", lambda *_: outputs.popleft())
    monkeypatch.setattr(opencode, "runner_started", lambda *_: None)
    monkeypatch.setattr(opencode, "runner_finished", lambda *_: None)
    return commands, prompts


STOP = b'{"type":"step_finish","sessionID":"sid","part":{"reason":"stop"}}\n'


def test_steer_runs_as_next_session_turn(monkeypatch, tmp_path):
    state_path, job = tmp_path / "state.json", tmp_path
    st = state(tmp_path)
    (job / "steer").mkdir()
    (job / "steer" / "001.md").write_text("next turn")
    commands, prompts = fake_turns(monkeypatch, [STOP + b"{partial", b"", STOP, b""], [0, 0])
    opencode.run(job, st, state_path, "first prompt")
    assert len(commands) == 2
    assert "first prompt" not in commands[0] and prompts[0].endswith(b"first prompt")
    assert "next turn" not in commands[1] and prompts[1] == b"next turn"
    assert commands[1][commands[1].index("--session") + 1] == "sid"
    assert not (job / "steer" / "001.md").exists()
    assert (job / "steer" / "sent" / "001.md").exists()
    kinds = [json.loads(line)["kind"] for line in (job / "live.jsonl").read_text().splitlines()]
    assert kinds.count("turn_completed") == 2  # one per process, not per model step


def test_denied_call_is_reported_and_worker_continues(monkeypatch, tmp_path):
    state_path, job = tmp_path / "state.json", tmp_path
    (job / "steer").mkdir()
    declined = {
        "type": "tool_use",
        "sessionID": "sid",
        "part": {
            "tool": "shell",
            "state": {"status": "error", "input": {"command": "cd /tmp"}, "error": opencode.DECLINED},
        },
    }
    aborted = {
        "type": "error",
        "sessionID": "sid",
        "error": {"type": "aborted", "message": "Step interrupted"},
    }
    first = (json.dumps(declined) + "\n" + json.dumps(aborted) + "\n").encode()
    commands, prompts = fake_turns(monkeypatch, [first, b"", STOP, b""], [1, 0])
    opencode.run(job, state(tmp_path), state_path, "first prompt")
    events = [json.loads(line) for line in (job / "live.jsonl").read_text().splitlines()]
    assert [e["denied"] for e in events if e["kind"] == "permission_denied"] == [["cd /tmp"]]
    assert not any(e["kind"] == "error" for e in events)
    assert len(commands) == 2 and "auto-denied" in prompts[1].decode()


def test_denial_does_not_hide_provider_error(monkeypatch, tmp_path):
    declined = {
        "type": "tool_use",
        "part": {
            "tool": "shell",
            "state": {"status": "error", "input": {"command": "cd /tmp"}, "error": opencode.DECLINED},
        },
    }
    provider_error = {"type": "error", "error": {"type": "provider", "message": "quota exhausted"}}
    output = (json.dumps(declined) + "\n" + json.dumps(provider_error) + "\n").encode()
    fake_turns(monkeypatch, [output, b""], [1])
    with pytest.raises(RuntimeError, match="opencode exited"):
        opencode.run(tmp_path, state(tmp_path), tmp_path / "state.json", "prompt")
    events = [json.loads(line) for line in (tmp_path / "live.jsonl").read_text().splitlines()]
    assert any(event["kind"] == "error" and "quota exhausted" in event["message"] for event in events)


def test_missing_finish_and_missing_resume_session_are_reported(monkeypatch, tmp_path):
    # a reply without step events is a completed turn; exit 0 with nothing is reported, not fatal
    reply, empty = b'{"type":"text","part":{"text":"reply"}}\n', b'{"type":"step_start","part":{}}\n'
    fake_turns(monkeypatch, [reply, b"", empty, b""], [0, 0])
    opencode.run(tmp_path / "a", state(tmp_path), tmp_path / "a.json", "prompt")
    opencode.run(tmp_path / "b", state(tmp_path), tmp_path / "b.json", "prompt")
    done = [json.loads(line) for line in (tmp_path / "a/live.jsonl").read_text().splitlines()]
    assert [e["status"] for e in done if e["kind"] == "turn_completed"] == ["completed"]
    events = [json.loads(line) for line in (tmp_path / "b/live.jsonl").read_text().splitlines()]
    assert any(event["kind"] == "turn_completed" and event["status"] == "incomplete" for event in events)
    assert any(event["kind"] == "error" and event["level"] == "urgent" for event in events)

    with pytest.raises(RuntimeError, match="session ID is missing"):
        opencode.run(
            tmp_path, {**state(tmp_path), "sessionId": ""}, tmp_path / "resume.json", "again", resume=True
        )

    (tmp_path / "steer").mkdir(exist_ok=True)
    (tmp_path / "steer" / "001.md").write_text("next")
    fake_turns(monkeypatch, [STOP, b"", b'{"type":"step_finish"}\n', b""], [0, 0])
    with pytest.raises(RuntimeError, match="turn had no session ID"):
        opencode.run(tmp_path, state(tmp_path), tmp_path / "state2.json", "prompt")

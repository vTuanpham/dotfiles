import json
from collections import deque

import pytest

from agent_bridge import claude


class FakeInput:
    def __init__(self):
        self.closed = False
        self.lines = []

    def write(self, value):
        self.lines.append(value)

    def flush(self):
        pass

    def close(self):
        self.closed = True


class FakeProcess:
    def __init__(self, *args, **kwargs):
        self.stdin = FakeInput()
        self.stdout = type("Output", (), {"fileno": lambda self: 1})()
        self.returncode = 0
        self.pid = 999

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode


def fake_stream(monkeypatch, events):
    proc = FakeProcess()
    chunks = deque([(json.dumps(event) + "\n").encode() for event in events] + [b""])
    monkeypatch.setattr(claude.subprocess, "Popen", lambda *a, **kw: proc)
    monkeypatch.setattr(claude.select, "select", lambda *a: ([proc.stdout], [], []))
    monkeypatch.setattr(claude.os, "read", lambda *a: chunks.popleft())
    monkeypatch.setattr(claude, "runner_started", lambda state, path: None)
    monkeypatch.setattr(claude, "runner_finished", lambda state, path: None)
    return proc


def make_state(tmp_path):
    state = {
        "sessionId": "sid",
        "cwd": str(tmp_path),
        "writableRoots": [str(tmp_path)],
        "sandbox": "workspace-write",
    }
    return state, tmp_path / "state.json"


def test_claude_settings_and_event_mapping(tmp_path, capsys):
    state, _ = make_state(tmp_path)
    cmd = claude.command(state, tmp_path, resume=True)
    assert "Agent" in cmd
    assert "--replay-user-messages" in cmd
    settings = json.loads((tmp_path / "claude-settings.json").read_text())
    assert settings["permissions"]["allow"] == ["WebFetch(domain:*)"]
    assert settings["env"]["CLAUDE_CODE_PLUGIN_DIRS"] == ""
    assert settings["sandbox"]["failIfUnavailable"] is True
    state["sandbox"] = "read-only"
    cmd = claude.command(state, tmp_path)
    assert json.loads((tmp_path / "claude-settings.json").read_text())["permissions"] == {}
    assert cmd.count("--disallowedTools") == 1
    assert all(tool in cmd for tool in ("Agent", "Edit", "Write", "NotebookEdit"))
    assert claude.models() is None
    assert capsys.readouterr().out.splitlines() == [
        "sonnet\t-\talias",
        "opus\t-\talias",
        "haiku\t-\talias",
    ]


def test_midturn_steer_needs_only_one_result_to_close_stdin(monkeypatch, tmp_path):
    state, path = make_state(tmp_path)
    (tmp_path / "steer").mkdir()
    (tmp_path / "steer" / "001.md").write_text("steer now")
    proc = fake_stream(
        monkeypatch,
        [
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "working"}]}},
            {"type": "result", "queued_turn_count": 0, "subtype": "success"},
            {
                "type": "user",
                "message": {"role": "user", "content": "steer now"},
                "parent_tool_use_id": None,
            },
            {"type": "result", "queued_turn_count": 0, "subtype": "success"},
        ],
    )
    claude.run(tmp_path, state, path, "start")
    assert proc.stdin.closed
    assert len(proc.stdin.lines) == 2
    assert state["activeTurnId"] is None


def test_unsolicited_turn_after_idle_is_logged_until_eof(monkeypatch, tmp_path):
    state, path = make_state(tmp_path)
    proc = fake_stream(
        monkeypatch,
        [
            {"type": "result", "queued_turn_count": 0, "subtype": "success"},
            {"type": "system", "subtype": "init", "session_id": "sid"},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "background finished"}]}},
            {"type": "result", "queued_turn_count": 0, "subtype": "success"},
        ],
    )
    claude.run(tmp_path, state, path, "start")
    assert proc.stdin.closed
    logged = [json.loads(line) for line in (tmp_path / "live.jsonl").read_text().splitlines()]
    assert sum(event["kind"] == "turn_completed" for event in logged) == 2
    assert any(event.get("text") == "background finished" for event in logged)


def test_eof_while_active_fails_and_logs_urgent(monkeypatch, tmp_path):
    state, path = make_state(tmp_path)
    fake_stream(monkeypatch, [])
    with pytest.raises(RuntimeError, match="claude exited mid-turn"):
        claude.run(tmp_path, state, path, "start")
    events = [json.loads(line) for line in (tmp_path / "live.jsonl").read_text().splitlines()]
    errors = [event for event in events if event["kind"] == "error"]
    assert len(errors) == 1 and errors[0]["level"] == "urgent"


def test_empty_resume_exits_when_stream_is_idle(monkeypatch, tmp_path):
    state, path = make_state(tmp_path)
    spawned = []

    def fail_spawn(*args, **kwargs):
        spawned.append(True)
        raise AssertionError("empty resume spawned Claude")

    monkeypatch.setattr(claude.subprocess, "Popen", fail_spawn)
    claude.run(tmp_path, state, path, "", resume=True)
    assert not spawned


def test_urgent_peer_message_routes_without_prefix(tmp_path):
    job = tmp_path / "owner" / "worker"
    peer = job.parent / "peer"
    job.mkdir(parents=True)
    peer.mkdir()
    (peer / "state.json").write_text("{}")
    claude.process(
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "URGENT: TO peer: check"}]}},
        {},
        job,
    )
    assert (peer / "steer" / "001.md").read_text() == "[from worker] check\n"


def test_echoed_user_message_confirms_inflight_steer(tmp_path):
    (tmp_path / "steer").mkdir()
    (tmp_path / "steer/001.md").write_text("confirmed steer")
    state = {"inflight": {"id": "steer-001", "file": "001.md"}}
    (tmp_path / "state.json").write_text(json.dumps(state))
    # a replayed prompt with no steer in flight, and a tool result while one is, are ordinary events
    claude.process({"type": "user", "message": {"role": "user", "content": "the prompt"}}, {}, tmp_path)
    result = {"type": "tool_result", "tool_use_id": "t1", "content": "ok"}
    claude.process({"type": "user", "message": {"role": "user", "content": [result]}}, state, tmp_path)
    assert state["inflight"] and '"command_end"' in (tmp_path / "live.jsonl").read_text()
    claude.process(
        {
            "type": "user",
            "message": {"role": "user", "content": "confirmed steer"},
            "parent_tool_use_id": None,
        },
        state,
        tmp_path,
    )
    assert state["inflight"] is None
    assert (tmp_path / "steer/sent/001.md").is_file()

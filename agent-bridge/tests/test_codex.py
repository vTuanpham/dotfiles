import json
from collections import deque
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_bridge import codex


class FakeRpc:
    def __init__(self, cwd, stderr, events=(), turns=()):
        self.events = deque(events)
        self.turns = turns
        self.sent = []
        self.calls = []

    def call(self, method, params=None):
        self.calls.append((method, params or {}))
        return {
            "thread/start": {"thread": {"id": "thread-1"}},
            "thread/resume": {"thread": {"id": "thread-1"}},
            "thread/turns/list": {"data": self.turns},
            "turn/start": {"turn": {"id": "turn-1"}},
            "turn/steer": {"turnId": "turn-1"},
        }.get(method, {})

    def send(self, message):
        self.sent.append(message)

    def read(self, timeout=None):
        return self.events.popleft() if self.events else None

    def close(self):
        pass


def job_state(tmp_path):
    job = tmp_path / "owner" / "job"
    job.mkdir(parents=True)
    (job / "steer").mkdir()
    (job / "inbox").mkdir()
    (job / "home" / "codex").mkdir(parents=True)
    path = job / "state.json"
    state = {
        "version": 1,
        "backend": "codex",
        "cwd": str(tmp_path),
        "threadId": "",
        "sandbox": "read-only",
        "writableRoots": [],
    }
    path.write_text(json.dumps(state))
    return job, path, state


def test_active_account_records_only_codex_auth_number(monkeypatch):
    monkeypatch.setattr(
        codex.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            stdout="* 3 Pro person@example.com\n  4 Free other@example.com\n"
        ),
    )
    assert codex.active_account() == "3"


def test_model_catalog_parser_lists_supported_ids_and_efforts():
    catalog = json.dumps(
        {
            "models": [
                {
                    "slug": "model-a",
                    "visibility": "list",
                    "supported_reasoning_levels": [{"effort": "low"}, {"effort": "high"}],
                },
                {"slug": "hidden", "visibility": "hide", "supported_reasoning_levels": []},
            ]
        }
    )
    assert codex.parse_models(catalog) == ["model-a\tlow,high"]


def test_rpc_closes_stderr_when_process_start_fails(monkeypatch, tmp_path):
    stderr = tmp_path / "stderr.log"
    opened = []
    original_open = Path.open

    def track_open(path, *args, **kwargs):
        stream = original_open(path, *args, **kwargs)
        if path == stderr:
            opened.append(stream)
        return stream

    monkeypatch.setattr(Path, "open", track_open)
    monkeypatch.setattr(
        codex.subprocess, "Popen", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("missing"))
    )
    with pytest.raises(OSError, match="missing"):
        codex.Rpc(tmp_path, stderr)
    assert opened[0].closed


def test_event_mapping_and_inbox(monkeypatch, tmp_path):
    job, path, state = job_state(tmp_path)
    (job / "inbox" / "7.md").write_text("answer")
    peer = job.parent / "peer"
    peer.mkdir()
    (peer / "state.json").write_text("{}")
    events = [
        {"method": "item/completed", "params": {"item": {"type": "agentMessage", "text": "URGENT: help"}}},
        {
            "method": "item/completed",
            "params": {"item": {"type": "agentMessage", "text": "URGENT: TO peer: please check"}},
        },
        {
            "method": "item/started",
            "params": {"turnId": "turn-1", "item": {"type": "commandExecution", "command": "ls"}},
        },
        {
            "method": "item/completed",
            "params": {
                "turnId": "turn-1",
                "item": {"type": "commandExecution", "status": "completed", "exitCode": 0},
            },
        },
        {"id": 7, "method": "item/tool/requestUserInput", "params": {"questions": [{"id": "q1"}]}},
        {
            "id": 8,
            "method": "item/commandExecution/requestApproval",
            "params": {"turnId": "turn-1", "command": "rm"},
        },
        {"id": 9, "method": "item/permissions/requestApproval", "params": {}},
        {"method": "turn/started", "params": {"turn": {"id": "turn-1"}}},
        {"method": "turn/completed", "params": {"turn": {"id": "turn-1", "status": "completed"}}},
    ]
    rpc = FakeRpc(state["cwd"], job / "stderr", events)
    monkeypatch.setattr(codex, "Rpc", lambda *args: rpc)
    monkeypatch.setattr(codex, "runner_started", lambda state, path: None)
    monkeypatch.setattr(codex, "runner_finished", lambda state, path: None)
    codex.run(job, state, path, "prompt")
    logged = [json.loads(line) for line in (job / "live.jsonl").read_text().splitlines()]
    kinds = [event["kind"] for event in logged]
    assert kinds[:6] == ["message", "message", "peer_sent", "command_start", "command_end", "question"]
    assert "question_answered" in kinds
    assert logged[0]["level"] == "urgent"
    assert "turn_completed" in kinds and "approval_declined" in kinds
    approval = next(event for event in logged if event["kind"] == "approval_declined")
    assert approval["command"] == "rm" and approval["turnId"] == "turn-1"
    start = next(event for event in logged if event["kind"] == "command_start")
    assert start["turnId"] == "turn-1"
    assert state["lastTurnId"] == "turn-1"
    assert {"id": 7, "result": {"answers": {"q1": {"answers": ["answer"]}}}} in rpc.sent
    assert {"id": 8, "result": {"decision": "decline"}} in rpc.sent
    assert {"id": 9, "result": {"permissions": {}}} in rpc.sent
    assert (peer / "steer" / "001.md").read_text() == "[from job] please check\n"


def test_resume_known_steer_recovery_and_dedup(monkeypatch, tmp_path):
    job, path, state = job_state(tmp_path)
    state.update(threadId="thread-1", inflight={"id": "steer-001", "file": "001.md"})
    (job / "steer" / "001.md").write_text("already delivered")
    (job / "steer" / "002.md").write_text("also delivered")
    rpc = FakeRpc(
        state["cwd"],
        job / "stderr",
        turns=[{"status": "completed", "items": [{"clientId": "steer-001"}, {"clientId": "steer-002"}]}],
    )
    monkeypatch.setattr(codex, "Rpc", lambda *args: rpc)
    monkeypatch.setattr(codex, "runner_started", lambda state, path: None)
    monkeypatch.setattr(codex, "runner_finished", lambda state, path: None)
    codex.run(job, state, path, "", resume=True)
    assert (job / "steer" / "sent" / "001.md").is_file()
    assert (job / "steer" / "sent" / "002.md").is_file()
    assert not any(method in ("turn/start", "turn/steer") for method, _ in rpc.calls)
    assert "thread/turns/list" in [method for method, _ in rpc.calls]
    assert not any("archive" in method for method, _ in rpc.calls)


def test_resume_unknown_inflight_fails(monkeypatch, tmp_path):
    job, path, state = job_state(tmp_path)
    state.update(threadId="thread-1", inflight={"id": "steer-001", "file": "001.md"})
    (job / "steer" / "001.md").write_text("uncertain")
    rpc = FakeRpc(state["cwd"], job / "stderr")
    monkeypatch.setattr(codex, "Rpc", lambda *args: rpc)
    monkeypatch.setattr(codex, "runner_started", lambda state, path: None)
    monkeypatch.setattr(codex, "runner_finished", lambda state, path: None)
    with pytest.raises(RuntimeError, match="steer delivery is uncertain"):
        codex.run(job, state, path, "", resume=True)


def test_resolved_server_request_is_removed_from_pending(monkeypatch, tmp_path):
    job, path, state = job_state(tmp_path)
    state.update(threadId="thread-1")
    rpc = FakeRpc(
        state["cwd"],
        job / "stderr",
        events=[
            {"id": 7, "method": "item/tool/requestUserInput", "params": {"questions": [{"id": "q1"}]}},
            {"method": "serverRequest/resolved", "params": {"requestId": "7"}},
        ],
    )
    rpc.read = lambda timeout=None: {"eof": True}
    monkeypatch.setattr(codex, "Rpc", lambda *args: rpc)
    monkeypatch.setattr(codex, "runner_started", lambda state, path: None)
    monkeypatch.setattr(codex, "runner_finished", lambda state, path: None)
    codex.run(job, state, path, "", resume=True)
    assert not any(message.get("id") == 7 for message in rpc.sent)


@pytest.mark.parametrize("queued", [False, True])
def test_compact_waits_until_compaction_turn_completes(monkeypatch, tmp_path, queued):
    job, path, state = job_state(tmp_path)
    state["threadId"] = "thread-1"
    if queued:
        (job / "steer/001.md").write_text("follow up")
    rpc = FakeRpc(
        state["cwd"],
        job / "stderr",
        events=[
            {"method": "item/completed", "params": {"item": {"type": "contextCompaction"}}},
            {"method": "turn/started", "params": {"turn": {"id": "compact-turn"}}},
            {"method": "turn/completed", "params": {"turn": {"id": "compact-turn", "status": "completed"}}},
        ],
    )
    monkeypatch.setattr(codex, "Rpc", lambda *args: rpc)
    monkeypatch.setattr(codex, "runner_started", lambda state, path: None)
    monkeypatch.setattr(codex, "runner_finished", lambda state, path: None)
    codex.run(job, state, path, "", resume=True, compact=True)
    assert "thread/compact/start" in [method for method, _ in rpc.calls]
    assert "compacted" in [json.loads(line)["kind"] for line in (job / "live.jsonl").read_text().splitlines()]
    assert not any(method in ("turn/start", "turn/steer") for method, _ in rpc.calls)
    if queued:
        assert (job / "steer/001.md").read_text() == "follow up"


def fake_real_home(tmp_path, monkeypatch, account="a", refreshed="2026-01-01"):
    real = tmp_path / "real"
    (real / "skills").mkdir(parents=True)
    (real / "sessions").mkdir()
    (real / "AGENTS.md").write_text("rules")
    (real / "config.toml").write_text("model = 'x'")
    (real / "auth.json").write_text(
        json.dumps({"tokens": {"account_id": account}, "last_refresh": refreshed})
    )
    monkeypatch.setenv("CODEX_HOME", str(real))
    return real


def test_build_home_isolates_threads_and_shares_config(tmp_path, monkeypatch):
    real = fake_real_home(tmp_path, monkeypatch)
    (tmp_path / "job").mkdir()
    home = codex.build_home(tmp_path / "job")
    assert (home / "skills").is_symlink() and (home / "AGENTS.md").is_symlink()
    assert not (home / "sessions").exists() and not (home / "config.toml").is_symlink()
    assert (home / "auth.json").is_symlink() and (home / "config.toml").read_text() == "model = 'x'"
    (home / "config.toml").write_text("trusted")  # codex writes here
    (home / "sessions").mkdir()
    (home / "sessions" / "rollout.jsonl").write_text("thread")
    assert (real / "config.toml").read_text() == "model = 'x'"
    assert list((real / "sessions").iterdir()) == []


def test_sync_auth_hands_back_a_same_account_refresh_only(tmp_path, monkeypatch):
    real = fake_real_home(tmp_path, monkeypatch)
    job = tmp_path / "job"
    job.mkdir()
    home = codex.build_home(job)
    (home / "auth.json").unlink()
    refreshed = json.dumps({"tokens": {"account_id": "a"}, "last_refresh": "2026-02-01"})
    (home / "auth.json").write_text(refreshed)  # a refresh that replaced the symlink
    codex.sync_auth(job)
    assert (real / "auth.json").read_text() == refreshed and (home / "auth.json").is_symlink()
    assert (real / "auth.json").stat().st_mode & 0o777 == 0o600
    assert not list(real.glob(".auth.json.*"))
    (home / "auth.json").unlink()
    (home / "auth.json").write_text(json.dumps({"tokens": {"account_id": "b"}, "last_refresh": "2026-03-01"}))
    codex.sync_auth(job)
    assert json.loads((real / "auth.json").read_text())["tokens"]["account_id"] == "a"
    assert "auth_detached" in (job / "live.jsonl").read_text()
    (home / "auth.json").unlink()
    (home / "auth.json").write_text(json.dumps({"tokens": {"account_id": "a"}, "last_refresh": "2026-04-01"}))
    codex.build_home(job)  # a resume after a killed runner hands the refresh back too
    assert json.loads((real / "auth.json").read_text())["last_refresh"] == "2026-04-01"
    assert (home / "auth.json").is_symlink()


def test_build_home_survives_a_dangling_login_link_and_refreshes_config(tmp_path, monkeypatch):
    real = fake_real_home(tmp_path, monkeypatch)
    job = tmp_path / "job"
    job.mkdir()
    codex.build_home(job)
    (real / "auth.json").unlink()  # codex-auth swaps the file under a running job
    (real / "config.toml").write_text("model = 'y'")
    home = codex.build_home(job)
    assert (home / "auth.json").is_symlink() and not (home / "auth.json").exists()
    assert (home / "config.toml").read_text() == "model = 'y'"

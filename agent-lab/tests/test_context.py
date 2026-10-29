import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from agent_lab.cli import actor, parser
from agent_lab.context import Context, claude_session, infer

SESSION = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def codex_db(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as db:
        db.execute("CREATE TABLE threads (id TEXT PRIMARY KEY, model TEXT, reasoning_effort TEXT)")
        db.executemany(
            "INSERT INTO threads VALUES (?, ?, ?)",
            [(SESSION, "exact-model", "high"), ("nearby", "wrong-model", "low")],
        )
        db.commit()


def test_current_codex_model_is_exact_and_refreshes_after_a_switch(monkeypatch):
    home = Path(os.environ["CODEX_HOME"])
    codex_db(home / "state_5.sqlite")
    (home / "config.toml").write_text('model = "wrong-global-default"\n')
    monkeypatch.setenv("CODEX_THREAD_ID", SESSION)
    assert infer() == Context("codex", SESSION, "exact-model", "high")
    with closing(sqlite3.connect(home / "state_5.sqlite")) as db:
        db.execute(
            "UPDATE threads SET model=?, reasoning_effort=? WHERE id=?", ("switched-model", "xhigh", SESSION)
        )
        db.commit()
    assert infer() == Context("codex", SESSION, "switched-model", "xhigh")


def test_codex_profile_sqlite_override_and_missing_state(monkeypatch, tmp_path):
    monkeypatch.setenv("CODEX_THREAD_ID", SESSION)
    home = Path(os.environ["CODEX_HOME"])
    assert infer() == Context("codex", SESSION)
    assert not home.exists()  # read-only inference must not create native state
    home.mkdir()
    other = tmp_path / "sqlite"
    codex_db(other / "state_5.sqlite")
    (home / "config.toml").write_text(f"sqlite_home = {json.dumps(str(other))}\n")
    assert infer().model == "exact-model"
    (home / "config.toml").write_text('sqlite_home = "relative"\n')
    assert infer() == Context("codex", SESSION)


@pytest.mark.parametrize(
    "backend,key",
    [("codex", "threadId"), ("claude", "sessionId"), ("agy", "conversationId"), ("opencode", "sessionId")],
)
def test_bridge_workers_do_not_inherit_their_roots_identity(monkeypatch, backend, key):
    monkeypatch.setenv("CODEX_THREAD_ID", "coordinator")
    monkeypatch.setenv("AGENT_BRIDGE_WORKER", "1")
    monkeypatch.setenv("AGENT_BRIDGE_JOB", "owner/worker")
    path = Path(os.environ["AGENT_BRIDGE_HOME"]) / "jobs/owner/worker/state.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"backend": backend, key: SESSION, "model": "worker-model", "effort": "high"}))
    assert infer() == Context(backend, SESSION, "worker-model", "high")


def test_invalid_worker_binding_never_falls_back_to_coordinator(monkeypatch):
    monkeypatch.setenv("CODEX_THREAD_ID", "coordinator")
    monkeypatch.setenv("AGENT_BRIDGE_WORKER", "1")
    monkeypatch.setenv("AGENT_BRIDGE_JOB", "../../escape")
    assert infer() == Context()


@pytest.mark.parametrize(
    "damage", [{"backend": []}, {"backend": "codex", "model": False}, {"backend": "claude", "effort": 3}]
)
def test_malformed_worker_metadata_is_not_coerced(monkeypatch, damage):
    monkeypatch.setenv("CODEX_THREAD_ID", "coordinator")
    monkeypatch.setenv("AGENT_BRIDGE_WORKER", "1")
    monkeypatch.setenv("AGENT_BRIDGE_JOB", "owner/worker")
    path = Path(os.environ["AGENT_BRIDGE_HOME"]) / "jobs/owner/worker/state.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"threadId": SESSION, "sessionId": SESSION, **damage}))
    assert infer() == Context()


def test_claude_exact_session_model_and_synthetic_messages(monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", SESSION)
    monkeypatch.setenv("CODEX_THREAD_ID", "coordinator")
    directory = Path(os.environ["CLAUDE_CONFIG_DIR"]) / "projects/example"
    directory.mkdir(parents=True)
    records = [
        {"type": "assistant", "sessionId": SESSION, "message": {"model": "claude-actual"}},
        {"type": "assistant", "sessionId": "nearby", "message": {"model": "wrong-session"}},
        {"type": "assistant", "sessionId": SESSION, "message": {"model": "<synthetic>"}},
    ]
    (directory / f"{SESSION}.jsonl").write_text("\n".join(map(json.dumps, records)) + "\n")
    assert infer() == Context("claude", SESSION, "claude-actual", None)
    records.append({"type": "assistant", "sessionId": SESSION, "message": {"model": False}})
    (directory / f"{SESSION}.jsonl").write_text("\n".join(map(json.dumps, records)) + "\n")
    assert infer() == Context("claude", SESSION)
    (directory / f"{SESSION}.jsonl").write_text("not JSON\n")
    assert infer() == Context("claude", SESSION)


def test_claude_session_comes_from_its_actual_parent_process(monkeypatch, tmp_path):
    monkeypatch.setattr(os, "getppid", lambda: 42)
    home, proc = tmp_path / "native", tmp_path / "proc"
    registry = home / "sessions/42.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(json.dumps({"pid": 42, "sessionId": SESSION}))
    process = proc / "42"
    process.mkdir(parents=True)
    (process / "comm").write_text("claude\n")
    (process / "stat").write_text("42 (claude) S 1")
    assert claude_session(home, proc) == SESSION
    registry.write_text(json.dumps({"pid": 43, "sessionId": "wrong-process"}))
    assert claude_session(home, proc) is None


def test_native_antigravity_conversation_does_not_use_inherited_codex_identity(monkeypatch):
    monkeypatch.setenv("ANTIGRAVITY_CONVERSATION_ID", SESSION)
    monkeypatch.setenv("CODEX_THREAD_ID", "coordinator")
    assert infer() == Context("agy", SESSION)
    monkeypatch.setenv("ANTIGRAVITY_CONVERSATION_ID", "../../invalid")
    assert infer() == Context("agy")


def test_explicit_identity_override_does_not_reuse_detected_models(monkeypatch):
    monkeypatch.setenv("CODEX_THREAD_ID", SESSION)
    codex_db(Path(os.environ["CODEX_HOME"]) / "state_5.sqlite")
    args = parser().parse_args(["new", "probe", "--purpose", "test"])
    assert actor(args).model == "exact-model"
    args = parser().parse_args(["new", "probe", "--purpose", "test", "--session", "different"])
    assert actor(args).session == "different"
    assert actor(args).model is None
    args = parser().parse_args(["new", "probe", "--purpose", "test", "--model", "override"])
    assert actor(args).model == "override"


@pytest.mark.parametrize("damage", ["broken-schema", "bad-model", "bad-config"])
def test_unavailable_native_metadata_stays_unknown(monkeypatch, damage):
    monkeypatch.setenv("CODEX_THREAD_ID", SESSION)
    home = Path(os.environ["CODEX_HOME"])
    codex_db(home / "state_5.sqlite")
    if damage == "bad-config":
        (home / "config.toml").write_text("[not valid")
    else:
        with closing(sqlite3.connect(home / "state_5.sqlite")) as db:
            if damage == "broken-schema":
                db.execute("DROP TABLE threads")
            else:
                db.execute("UPDATE threads SET model=123 WHERE id=?", (SESSION,))
            db.commit()
    result = infer()
    if damage == "bad-model":
        # SQLite's TEXT affinity stores this as text; malformed typed values use a BLOB instead.
        with closing(sqlite3.connect(home / "state_5.sqlite")) as db:
            db.execute("UPDATE threads SET model=? WHERE id=?", (b"invalid", SESSION))
            db.commit()
        result = infer()
    assert result == Context("codex", SESSION)

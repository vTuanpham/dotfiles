import json

from agent_bridge import cli


def test_bindings_cover_all_harnesses_and_owners_without_private_state(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "JOBS", tmp_path)
    for index, (backend, key) in enumerate([
        ("codex", "threadId"), ("claude", "sessionId"),
        ("agy", "conversationId"), ("opencode", "sessionId"),
    ]):
        folder = tmp_path / ("owner" + str(index)) / "worker"
        folder.mkdir(parents=True)
        (folder / "state.json").write_text(json.dumps({
            "backend": backend, key: "session-" + backend, "title": "Worker",
            "account": "private-account", "config": {"secret": "private-token"},
            "parent": {"backend": "codex", "session_id": "parent-root"},
        }))
    result = cli.session_bindings()
    assert result["version"] == 1 and len(result["sessions"]) == 4
    assert {row["backend"] for row in result["sessions"]} == {"codex", "claude", "agy", "opencode"}
    assert all(row["parent"]["session_id"] == "parent-root" for row in result["sessions"])
    assert "private" not in json.dumps(result)
    assert all(set(row) == {"backend", "session_id", "job", "title", "parent"} for row in result["sessions"])


def test_root_identity_records_the_real_launcher_or_explicit_other_harness(monkeypatch):
    monkeypatch.setenv("CODEX_THREAD_ID", "codex-root")
    monkeypatch.delenv("CLAUDECODE", raising=False)
    assert cli.root_identity() == {"backend": "codex", "session_id": "codex-root"}
    monkeypatch.delenv("CODEX_THREAD_ID")
    monkeypatch.setenv("AGENT_BRIDGE_ROOT_HARNESS", "opencode")
    monkeypatch.setenv("AGENT_BRIDGE_ROOT_SESSION", "other-root")
    assert cli.root_identity() == {"backend": "opencode", "session_id": "other-root"}
    monkeypatch.delenv("AGENT_BRIDGE_ROOT_SESSION")
    assert cli.root_identity() is None

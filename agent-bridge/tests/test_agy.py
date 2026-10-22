import json
from types import SimpleNamespace

from agent_bridge import agy
from agent_bridge.agy import process


def test_stream_event_mapping_and_denial_continuation(tmp_path):
    state = {"conversationId": "c1", "turnsSent": 1, "turnsDone": 0}
    sent = []
    send = sent.append
    process({"event": "init", "conversation_id": "c1", "init": {"model": "model-x"}}, state, tmp_path, send)
    assert json.loads((tmp_path / "state.json").read_text())["conversationId"] == "c1"
    process(
        {
            "event": "step_update",
            "step_update": {
                "step_type": "agent_response",
                "step_index": 1,
                "text_delta": "URGENT: blocked",
                "state": "DONE",
            },
        },
        state,
        tmp_path,
        send,
    )
    process(
        {
            "event": "step_update",
            "step_update": {
                "step_type": "tool",
                "tool_name": "Bash",
                "state": "ACTIVE",
                "tool_info": {"parameters": {"CommandLine": "ls"}},
            },
        },
        state,
        tmp_path,
        send,
    )
    denied = [{"action": "write_file", "target": "/outside"}]
    process(
        {"event": "result", "result": {"status": "completed", "denied_actions": denied}},
        state,
        tmp_path,
        send,
    )
    logged = [json.loads(line) for line in (tmp_path / "live.jsonl").read_text().splitlines()]
    assert [event["kind"] for event in logged] == [
        "thread_started",
        "message",
        "command_start",
        "turn_completed",
        "permission_denied",
    ]
    assert logged[1]["level"] == "urgent"
    assert len(sent) == 1 and "Continue without them" in sent[0]
    assert state["turnsDone"] == 1 and state["turnsSent"] == 1
    persisted = json.loads((tmp_path / "state.json").read_text())
    assert persisted["activeTurnId"] is None
    assert "_texts" not in persisted
    quota_error = "Individual quota reached. Resets in 4h50m"
    process(
        {"event": "result", "result": {"status": "ERROR", "response": quota_error}},
        {"turnsSent": 1, "turnsDone": 0},
        tmp_path,
        send,
    )
    last = json.loads((tmp_path / "live.jsonl").read_text().splitlines()[-1])
    assert last["kind"] == "turn_completed" and last["error"] == quota_error


def test_quota_without_account_refreshes_all_signed_in_accounts(monkeypatch, tmp_path, capsys):
    accounts = tmp_path / "accounts"
    for name in ("a1", "a2", "not-signed-in"):
        (accounts / name / agy.TOKEN).parent.mkdir(parents=True)
        if name != "not-signed-in":
            (accounts / name / agy.TOKEN).write_text("token")
    calls = []

    def run(command, **kwargs):
        calls.append(kwargs["cwd"])
        return SimpleNamespace(stdout='{"response":"Group\\t10\\t90%\\ttomorrow"}', stderr="")

    monkeypatch.setattr(agy, "ACCOUNTS", accounts)
    monkeypatch.setattr(agy.subprocess, "run", run)
    agy.quota()
    assert calls == [str(accounts / "a1"), str(accounts / "a2")]
    assert "a1\tGroup" in capsys.readouterr().out


def test_models_adds_unknown_effort_column(monkeypatch, capsys):
    monkeypatch.setattr(agy, "account_env", lambda _: {})
    monkeypatch.setattr(
        agy.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="gemini/model\tGemini model\n"),
    )
    agy.models()
    assert capsys.readouterr().out.splitlines() == ["gemini/model\t-\tcheap\tgemini\tGemini model"]


def test_result_confirms_only_the_inflight_steer_turn(tmp_path):
    (tmp_path / "steer").mkdir()
    (tmp_path / "steer/001.md").write_text("agy steer")
    state = {
        "turnsDone": 0,
        "turnsSent": 2,
        "inflight": {"id": "steer-001", "file": "001.md", "turnsSent": 2},
    }
    (tmp_path / "state.json").write_text(json.dumps(state))
    process(
        {"event": "result", "result": {"status": "completed"}},
        state,
        tmp_path,
        lambda _: None,
    )
    assert state["turnsDone"] == 1 and state["inflight"] is not None
    process(
        {"event": "result", "result": {"status": "completed"}},
        state,
        tmp_path,
        lambda _: None,
    )
    assert state["turnsDone"] == 2 and state["inflight"] is None
    assert (tmp_path / "steer/sent/001.md").is_file()


def test_build_home_never_touches_real_agy_store(tmp_path, monkeypatch):
    real, acct, job = tmp_path / "real", tmp_path / "acct", tmp_path / "job"
    store = real / ".gemini" / "antigravity-cli"
    store.mkdir(parents=True)
    (store / "history.db").write_text("mine")
    (real / ".gemini" / "other").write_text("shared")
    (real / ".zshrc").write_text("rc")
    (real / ".gemini" / "config" / "projects").mkdir(parents=True)
    (real / ".gemini" / "config" / "projects" / "p.json").write_text("stub")
    (real / ".gemini" / "config" / "mcp_config.json").write_text("{}")
    (acct / agy.TOKEN).parent.mkdir(parents=True)
    (acct / agy.TOKEN).write_text("tok")
    monkeypatch.setattr(agy.Path, "home", staticmethod(lambda: real))
    monkeypatch.setattr(agy, "ACCOUNTS", tmp_path / "accts")
    (tmp_path / "accts").symlink_to(tmp_path)
    job.mkdir()
    state = {"account": "acct", "cwd": "/w", "writableRoots": [], "sandbox": "read-only"}
    home = agy.build_home(job, state)
    cli = home / ".gemini" / "antigravity-cli"
    assert not cli.is_symlink() and not (cli / "history.db").exists()
    assert not (home / ".gemini").is_symlink() and (home / ".gemini" / "other").is_symlink()
    (cli / "history.db").write_text("worker")  # a worker writing its session
    assert (store / "history.db").read_text() == "mine"
    assert sorted(p.name for p in store.iterdir()) == ["history.db"]
    projects = home / ".gemini" / "config" / "projects"
    assert not projects.is_symlink() and (home / ".gemini" / "config" / "mcp_config.json").is_symlink()
    (projects / "p.json").write_text("rewritten")
    assert (real / ".gemini" / "config" / "projects" / "p.json").read_text() == "stub"

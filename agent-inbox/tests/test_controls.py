import concurrent.futures
import json
import sqlite3
import uuid

import pytest

from agent_inbox import (
    adapters,
    codex_commands,
    codex_context,
    codex_history,
    opencode_context,
    opencode_forms,
)
from agent_inbox.commands import Choice, Command, Commands
from agent_inbox.context import SessionContext
from agent_inbox.forms import Condition, FormField, Forms, QuestionForm
from agent_inbox.models import DeliveryRejected, Target
from agent_inbox.server import App
from agent_inbox.store import Store, digest


class Controls:
    def __init__(self):
        self.calls = []
        self.raise_after_dispatch = False

    def discover(self, seed):
        return None

    def commands(self, target):
        return Commands([Command("model", "Model", "select", [Choice(target.id, "Model")])])

    def forms(self, target):
        return Forms([QuestionForm(target.id, "Choose", [FormField("choice", "Choice", "boolean", True)])])

    def execute(self, target, command, value):
        self.calls.append((target.id, command, value))
        if self.raise_after_dispatch:
            raise TimeoutError()
        return "applied"

    def answer(self, target, identifier, answer, cancel):
        self.calls.append((target.id, identifier, answer, cancel))
        return "applied"


@pytest.fixture
def controls(tmp_path, monkeypatch):
    store, provider = Store(tmp_path / "state"), Controls()
    monkeypatch.setitem(adapters.ADAPTERS, "controls", provider)
    for identifier in ("first", "second"):
        store.register(Target(identifier, "controls", "Fixture", identifier, identifier, {}))
    return App(store), provider


def test_commands_are_root_bound_idempotent_and_do_not_retry_unknown(controls):
    app, provider = controls
    data = {"id": str(uuid.uuid4()), "target": "second", "command": "model", "value": "second"}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        states = list(pool.map(lambda _: app.command(data)["status"], range(4)))
    assert set(states) <= {"applied", "sending"}
    assert provider.calls == [("second", "model", "second")]
    with pytest.raises(ValueError):
        app.command({**data, "target": "first"})
    assert app.command({**data, "id": str(uuid.uuid4()), "value": "first"})["status"] == "failed"
    assert len(provider.calls) == 1
    provider.raise_after_dispatch = True
    data["id"] = str(uuid.uuid4())
    assert app.command(data)["status"] == app.command(data)["status"] == "unknown"
    assert len(provider.calls) == 2


def test_receipt_cannot_cross_operation_even_if_payload_hash_matches(controls):
    app, provider = controls
    identifier = str(uuid.uuid4())
    fingerprint = json.dumps(["command", "model", "second"], separators=(",", ":"))
    app.store.reserve(identifier, "second", fingerprint)
    with pytest.raises(ValueError):
        app.command({"id": identifier, "target": "second", "command": "model", "value": "second"})
    assert not provider.calls


def test_legacy_receipts_and_device_pairing_survive_operation_migration(tmp_path):
    identifier = str(uuid.uuid4())
    path = tmp_path / "inbox.sqlite3"
    with sqlite3.connect(path) as db:
        db.executescript("CREATE TABLE receipts "
                         "(id TEXT PRIMARY KEY,target TEXT,hash TEXT,status TEXT,created REAL);"
                         "CREATE TABLE devices (id TEXT PRIMARY KEY,name TEXT,hash TEXT,created REAL);"
                         "PRAGMA user_version=1;")
        db.execute("INSERT INTO receipts VALUES (?,?,?,?,?)",
                   (identifier, "root", digest("payload"), "unknown", 1))
        db.execute("INSERT INTO devices VALUES (?,?,?,?)", ("phone", "Phone", digest("device-token"), 1e12))
    store = Store(tmp_path)
    assert store.authenticated("device-token")
    assert store.reserve(identifier, "root", "payload") == (False, "unknown")
    with pytest.raises(ValueError):
        store.reserve(identifier, "root", "payload", "command")


def test_question_answers_require_current_form_in_selected_root(controls):
    app, provider = controls
    data = {"id": str(uuid.uuid4()), "target": "second", "form": "first", "answer": {"choice": False}}
    assert app.answer(data)["status"] == "failed"
    assert not provider.calls
    data.update(id=str(uuid.uuid4()), form="second")
    assert app.answer(data)["status"] == app.answer(data)["status"] == "applied"
    assert provider.calls == [("second", "second", {"choice": False}, False)]
    assert app.answer({**data, "id": str(uuid.uuid4()), "answer": {}, "cancel": True})["status"] == "applied"
    with pytest.raises(ValueError):
        app.answer({**data, "cancel": True})


def test_conditional_forms_preserve_false_zero_and_multiselect_semantics():
    question = QuestionForm("f", "Form", [
        FormField("enabled", "Enabled", "boolean", True),
        FormField("count", "Count", "integer", True, when=[Condition("enabled", "eq", False)],
                  constraints={"minimum": 0, "maximum": 3}),
        FormField("tags", "Tags", "multiselect", choices=[Choice("a", "A"), Choice("b", "B")]),
        FormField("why", "Why", "string", True, when=[Condition("tags", "eq", "b")]),
    ])
    question.validate({"enabled": False, "count": 0})
    question.validate({"enabled": True, "tags": ["a", "b"], "why": "reason"})
    for answer in ({"enabled": False}, {"enabled": False, "count": True},
                   {"enabled": False, "count": float("inf")}, {"enabled": False, "count": 4},
                   {"enabled": True, "count": 0}, {"enabled": True, "tags": ["a", "a"]},
                   {"enabled": True, "tags": ["b"]}, {"enabled": True, "why": "inactive"}):
        with pytest.raises(DeliveryRejected):
            question.validate(answer)
    assert not FormField("x", "X", "string", when=[Condition("missing", "neq", "a")]).active({})


def test_native_forms_reject_wrong_root_duplicate_keys_and_external_controls():
    native = {"id": "frm_one", "sessionID": "ses_a", "title": "Choose", "fields": [
        {"key": "pick", "type": "string", "options": [{"value": "a", "label": "A"}], "required": True},
        {"key": "other", "type": "number", "when": [{"key": "pick", "op": "eq", "value": "a"}]},
    ]}
    decoded = opencode_forms.decode_form(native, "ses_a")
    decoded.validate({"pick": "a", "other": 0})
    with pytest.raises(ValueError):
        opencode_forms.decode_form(native, "ses_b")
    with pytest.raises(ValueError):
        opencode_forms.decode_form({**native, "fields": native["fields"] * 2}, "ses_a")
    external = opencode_forms.decode_form(
        {**native, "fields": [{"key": "auth", "type": "external"}]}, "ses_a")
    assert external.unavailable and not external.fields


class AccountRpc:
    def __init__(self):
        self.reads = 0
        self.changed = False
        self.limits = {"accountId": "account-a", "rateLimitsByLimitId": {"codex": {
            "primary": {"usedPercent": 104, "windowDurationMins": 300, "resetsAt": 1000}}}}

    def call(self, method, params):
        if method == "account/read":
            self.reads += 1
            return {"account": {"type": "chatgpt", "email": "account@example.test", "planType": "plus",
                                "id": "changed" if self.changed and self.reads > 1 else "original"}}
        assert method == "account/rateLimits/read"
        return self.limits


def test_quota_is_connection_scoped_and_published_only_after_consistent_read():
    rpc, result = AccountRpc(), SessionContext()
    codex_context.account(rpc, {"modelProvider": "openai"}, result)
    assert result.account.scope == "connection" and result.account.identity == "account-a"
    assert result.quotas[0].used_percent == 104
    for changed in (True, False):
        rpc, result = AccountRpc(), SessionContext()
        rpc.changed = changed
        if not changed:
            rpc.limits["rateLimitsByLimitId"]["codex"]["primary"]["usedPercent"] = True
        with pytest.raises(ValueError):
            codex_context.account(rpc, {"modelProvider": "openai"}, result)
        assert result.account is None and not result.quotas


def test_codex_workers_are_descendants_only_and_tools_use_selected_thread():
    class Rpc:
        def call(self, method, params):
            if method == "thread/loaded/list":
                return {"data": ["root", "child", "grandchild", "unrelated"]}
            if method == "thread/read":
                identifier = params["threadId"]
                return {"thread": {"id": identifier, "parentThreadId": {
                    "root": None, "child": "root", "grandchild": "child", "unrelated": "another",
                }[identifier], "status": {"type": "idle"}}}
            assert method == "mcpServerStatus/list" and params["threadId"] == "root"
            return {"data": [{"name": "fixture", "runtimeStatus": "ready", "tools": {"a": {}}}],
                    "nextCursor": None}

    assert {worker.id for worker in codex_context.workers(Rpc(), "root")} == {"child", "grandchild"}
    assert codex_context.tools(Rpc(), "root")[0].tool_count == 1


def test_codex_model_and_effort_apply_to_selected_root_future_turns():
    calls = []

    class Rpc:
        def call(self, method, params):
            calls.append((method, params))
            if method == "model/list":
                return {"data": [{"model": "m", "displayName": "Model",
                                  "supportedReasoningEfforts": [{"reasoningEffort": "high"}]}],
                        "nextCursor": None}
            return {}

    rpc = Rpc()
    catalog = codex_commands.commands(rpc, {"model": "m", "status": {"type": "idle"}})
    catalog.selected("effort", "high")
    selected = Target("t", "codex", "Codex", "native-root", "Root", {})
    codex_commands.execute(rpc, selected, "effort", "high")
    assert calls[-1] == ("thread/settings/update", {"threadId": "native-root", "effort": "high"})
    with pytest.raises(DeliveryRejected):
        catalog.selected("model", "invented")


def test_opencode_usage_is_session_data_not_account_allowance():
    metrics = opencode_context.usage({"cost": 0.02, "tokens": {
        "input": 10, "output": 4, "reasoning": 2, "cache": {"read": 6, "write": 0}}})
    assert [(m.label, m.value) for m in metrics][:2] == [("Input", 10), ("Output", 4)]
    with pytest.raises(ValueError):
        opencode_context.usage({"cost": True, "tokens": {
            "input": 10, "output": 4, "reasoning": 2, "cache": {"read": 6, "write": 0}}})


@pytest.mark.parametrize(("command", "label"), [
    ("/usr/bin/zsh -lc 'rtk test uv run pytest -q secret-project'", "pytest"),
    ('/bin/bash -lc "rtk git status --short"', "git status"),
    ("rtk proxy python -c 'print(private_value)'", "python"),
    ("TOKEN=private-value curl https://example.test", "Terminal command"),
])
def test_command_labels_unwrap_native_shells_without_exposing_arguments(command, label):
    assert codex_history.command_label(command) == label

import asyncio
import base64
import io
import sys
import time
import uuid
from dataclasses import replace
from pathlib import Path
from threading import Lock, Thread
from types import SimpleNamespace

import pytest
from PIL import Image

from agent_inbox import acp, acp_history, acp_runtime
from agent_inbox.commands import Choice
from agent_inbox.models import DeliveryRejected, Outgoing, Target


def target(identifier="session-root"):
    return Target(
        "agy-root",
        "acp",
        "Antigravity",
        identifier,
        "Root",
        {
            "command": ["/opt/agy-acp", "--uid="],
            "bridge_backend": "agy",
        },
    )


def image_url():
    raw = io.BytesIO()
    Image.new("RGB", (2, 2), "#6ad8bf").save(raw, format="PNG")
    return "data:image/png;base64," + base64.b64encode(raw.getvalue()).decode()


def info(session_id="session-root", cwd="/project", **extra):
    return {"sessionId": session_id, "cwd": cwd, **extra}


def capabilities():
    return acp_history.initialize(
        {
            "protocolVersion": 1,
            "agentCapabilities": {
                "loadSession": True,
                "promptCapabilities": {"image": True},
                "sessionCapabilities": {"list": {}, "resume": {}},
            },
            "authMethods": [],
        }
    )


class FakePool:
    def __init__(self):
        self.sessions = [acp_history.Session("native-id-001", "/project", "Existing root", [])]
        self.calls = []
        self.active = False
        self.prompts = []
        self.options = [
            acp_history.ConfigOption(
                "model",
                "Model",
                "select",
                "model-a",
                "model",
                [("model-a", "A"), ("model-b", "B")],
            )
        ]
        self.modes = acp_history.Mode("code", [("code", "Code"), ("ask", "Ask")])
        self.available_commands = [acp_history.SlashCommand("test", "Run tests", "suite")]
        self.usage = None
        self.denied_permissions = 0

    def discover(self, selected):
        self.calls.append(("discover", selected))
        return list(self.sessions)

    def call(self, selected, operation, *arguments):
        assert selected.adapter == "acp"
        self.calls.append((operation, *arguments))
        if operation == "snapshot":
            return {
                "status": "active" if self.active else "unknown",
                "can_send": not self.active,
                "messages": [],
                "activity": [],
                "timeline": [],
            }
        if operation == "controls":
            return {
                "commands": self.available_commands,
                "modes": self.modes,
                "config_options": self.options,
                "active": self.active,
            }
        if operation == "context":
            return {"usage": self.usage, "denied_permissions": self.denied_permissions}
        if operation == "send":
            if self.active:
                raise DeliveryRejected("already active")
            self.prompts.append(arguments[0])
            return "end_turn"
        if operation == "slash":
            name, value = arguments
            self.prompts.append([{"type": "text", "text": "/" + name + (" " + value if value else "")}])
            return "end_turn"
        if operation == "cancel":
            if not self.active:
                raise DeliveryRejected("no active turn")
            self.active = False
            return "applied"
        if operation in ("config", "mode"):
            return "applied"
        raise AssertionError(operation)


def test_discovery_preserves_native_id_and_unknown_liveness():
    pool = FakePool()
    roots = acp.ACP(pool).discover(target("seed"))
    assert [(row.session_id, row.status, row.saved) for row in roots] == [
        ("native-id-001", "unknown", True),
    ]


def test_snapshot_uses_the_selected_persistent_root_and_forwards_cursors():
    pool = FakePool()
    selected = target("native-id-001")
    page = acp.ACP(pool).snapshot(selected, since='{"offset":1,"anchor":"m1"}')
    assert page.status == "unknown" and page.can_send
    assert pool.calls[-1] == ("snapshot", None, '{"offset":1,"anchor":"m1"}')


def test_send_keeps_native_image_blocks_and_returns_only_after_prompt_receipt():
    pool = FakePool()
    selected = target("native-id-001")
    message = Outgoing("96be83a6-314a-45d9-89cc-a0bc94508bc9", "Describe this", [image_url()])
    assert acp.ACP(pool).send(selected, message) == "completed"
    prompt = pool.prompts[0]
    assert prompt[0] == {"type": "text", "text": "Describe this"}
    assert prompt[1]["type"] == "image" and prompt[1]["mimeType"] == "image/png"
    assert base64.b64decode(prompt[1]["data"], validate=True)


def test_image_only_prompt_is_allowed_but_empty_prompt_is_rejected():
    provider, selected = acp.ACP(FakePool()), target("native-id-001")
    provider.send(selected, Outgoing("96be83a6-314a-45d9-89cc-a0bc94508bc9", "", [image_url()]))
    with pytest.raises(ValueError):
        provider.send(selected, Outgoing("96be83a6-314a-45d9-89cc-a0bc94508bc9", "", []))


def test_acp_explicitly_rejects_steering_instead_of_dispatching_a_second_prompt():
    pool = FakePool()
    with pytest.raises(DeliveryRejected, match="steering"):
        acp.ACP(pool).send(target("native-id-001"), Outgoing(str(uuid.uuid4()), "Hi", [], "steer"))
    assert not pool.prompts


def test_commands_are_limited_to_native_config_modes_slash_and_live_cancel():
    pool = FakePool()
    provider, selected = acp.ACP(pool), target("native-id-001")
    commands = provider.commands(selected)
    assert [item.id for item in commands.controls] == ["config:model", "mode", "slash:test"]
    assert commands.controls[0].choices == [Choice("model-a", "A"), Choice("model-b", "B")]
    assert provider.execute(selected, "config:model", "model-b") == "applied"
    assert pool.calls[-1] == ("config", "model", "model-b")
    assert provider.execute(selected, "mode", "ask") == "applied"
    assert provider.execute(selected, "slash:test", "unit") == "applied"
    assert pool.prompts[-1] == [{"type": "text", "text": "/test unit"}]
    with pytest.raises(DeliveryRejected):
        provider.execute(selected, "config:model", "made-up")


def test_cancel_is_only_exposed_for_this_actor_active_turn():
    pool = FakePool()
    provider, selected = acp.ACP(pool), target("native-id-001")
    with pytest.raises(DeliveryRejected):
        provider.execute(selected, "interrupt", "")
    pool.active = True
    assert provider.commands(selected).controls[-1].id == "interrupt"
    assert provider.execute(selected, "interrupt", "") == "applied"


def test_permission_forms_are_explicitly_declined_and_not_answerable():
    forms = acp.ACP(FakePool()).forms(target("native-id-001"))
    assert forms.forms == []
    assert "declined" in forms.unavailable


def test_context_projects_session_usage_without_inventing_account_quota():
    pool = FakePool()
    pool.usage = acp_history.Usage(45, 200, 0.25, "USD")
    pool.denied_permissions = 1
    context = acp.ACP(pool).context(target("native-id-001"))
    assert [(metric.label, metric.value, metric.unit) for metric in context.metrics] == [
        ("Context used", 45, "tokens"),
        ("Context window", 200, "tokens"),
        ("Session cost", 0.25, "USD"),
    ]
    assert context.quotas == [] and context.notices


def test_initialize_and_session_list_match_the_v1_advertised_legacy_shape():
    result = capabilities()
    assert (result.load, result.list, result.resume, result.image) == (True, True, True, True)
    page = acp_history.sessions_page({"sessions": [info("id/with:punctuation", title="Root")]})
    assert page.sessions[0].id == "id/with:punctuation"
    assert page.sessions[0].label == "Root"


def test_session_list_rejects_duplicate_or_non_absolute_root_metadata():
    with pytest.raises(ValueError, match="Duplicate"):
        acp_history.sessions_page({"sessions": [info(), info()]})
    with pytest.raises(ValueError, match="absolute"):
        acp_history.sessions_page({"sessions": [info(cwd="relative")]})


def test_history_combines_message_chunks_and_keeps_tools_interleaved():
    history = acp_history.History("session-root")
    history.update(
        {
            "sessionId": "session-root",
            "update": {
                "sessionUpdate": "user_message_chunk",
                "messageId": "user-1",
                "content": {"type": "text", "text": "Please "},
            },
        }
    )
    history.update(
        {
            "sessionId": "session-root",
            "update": {
                "sessionUpdate": "user_message_chunk",
                "messageId": "user-1",
                "content": {"type": "text", "text": "help"},
            },
        }
    )
    history.update(
        {
            "sessionId": "session-root",
            "update": {
                "sessionUpdate": "tool_call",
                "toolCallId": "tool-1",
                "title": "Reading files",
            },
        }
    )
    history.update(
        {
            "sessionId": "session-root",
            "update": {
                "sessionUpdate": "tool_call_update",
                "toolCallId": "tool-1",
                "status": "completed",
            },
        }
    )
    history.update(
        {
            "sessionId": "session-root",
            "update": {
                "sessionUpdate": "agent_message_chunk",
                "messageId": "agent-1",
                "content": {"type": "text", "text": "Done"},
            },
        }
    )
    messages, activity, timeline, older, newer, catching = history.page()
    assert [(message.role, message.text) for message in messages] == [
        ("user", "Please help"),
        ("assistant", "Done"),
    ]
    assert activity[0].status == "completed"
    assert timeline == ["acp:user-1", "activity:acp:tool-1", "acp:agent-1"]
    assert older is None and newer is not None and not catching


def test_history_renders_bounded_inline_images_and_tool_activity():
    history = acp_history.History("session-root")
    url = image_url()
    mime, _, encoded = url[5:].partition(";base64,")
    history.update(
        {
            "sessionId": "session-root",
            "update": {
                "sessionUpdate": "agent_message_chunk",
                "messageId": "agent-image",
                "content": {"type": "image", "mimeType": mime, "data": encoded},
            },
        }
    )
    messages, _, _, _, _, _ = history.page()
    assert messages[0].images == [url]


def test_history_rejects_foreign_sessions_unknown_updates_and_bad_cursors():
    history = acp_history.History("session-root")
    with pytest.raises(ValueError, match="another session"):
        history.update(
            {
                "sessionId": "other",
                "update": {
                    "sessionUpdate": "agent_message_chunk",
                    "content": {"type": "text", "text": "x"},
                },
            }
        )
    with pytest.raises(ValueError, match="Unsupported"):
        history.update({"sessionId": "session-root", "update": {"sessionUpdate": "future_update"}})
    with pytest.raises(ValueError):
        history.page(cursor='{"offset":1,"anchor":"missing"}')


def test_usage_update_tracks_context_and_session_cost_not_quota():
    history = acp_history.History("session-root")
    history.update(
        {
            "sessionId": "session-root",
            "update": {
                "sessionUpdate": "usage_update",
                "used": 128,
                "size": 4096,
                "cost": {"amount": 0.125, "currency": "USD"},
            },
        }
    )
    assert history.usage == acp_history.Usage(128, 4096, 0.125, "USD")


def test_config_options_and_slash_commands_reject_ambiguous_controls():
    history = acp_history.History("session-root")
    history.load(
        {
            "configOptions": [
                {
                    "id": "model",
                    "name": "Model",
                    "type": "select",
                    "currentValue": "one",
                    "options": [{"value": "one", "name": "One"}, {"value": "two", "name": "Two"}],
                }
            ]
        }
    )
    history.update(
        {
            "sessionId": "session-root",
            "update": {
                "sessionUpdate": "available_commands_update",
                "availableCommands": [
                    {"name": "test", "description": "Run tests", "input": {"hint": "suite"}},
                ],
            },
        }
    )
    assert history.config_options[0].current == "one"
    assert history.commands[0].hint == "suite"
    with pytest.raises(ValueError, match="command name"):
        history.update(
            {
                "sessionId": "session-root",
                "update": {
                    "sessionUpdate": "available_commands_update",
                    "availableCommands": [
                        {"name": "test; rm", "description": "Bad"},
                    ],
                },
            }
        )


def test_grouped_config_options_keep_native_choice_values():
    history = acp_history.History("session-root")
    history.load(
        {
            "configOptions": [
                {
                    "id": "model",
                    "name": "Model",
                    "type": "select",
                    "currentValue": "model-b",
                    "options": [
                        {
                            "group": "provider-a",
                            "name": "Provider A",
                            "options": [{"value": "model-a", "name": "Model A"}],
                        },
                        {
                            "group": "provider-b",
                            "name": "Provider B",
                            "options": [{"value": "model-b", "name": "Model B"}],
                        },
                    ],
                }
            ]
        }
    )
    assert history.config_options[0].current == "model-b"
    assert history.config_options[0].choices == [
        ("model-a", "Provider A · Model A"),
        ("model-b", "Provider B · Model B"),
    ]


def test_unknown_config_types_are_ignored_and_missing_categories_are_supported():
    history = acp_history.History("session-root")
    history.load(
        {
            "configOptions": [
                {"id": "future", "name": "Future", "type": "new-choice", "currentValue": "x"},
                {
                    "id": "model",
                    "name": "Model",
                    "type": "select",
                    "currentValue": "one",
                    "options": [{"value": "one", "name": "One"}],
                },
            ]
        }
    )
    assert [option.id for option in history.config_options] == ["model"]
    assert history.config_options[0].category is None


def test_boolean_config_update_requires_and_preserves_authoritative_state():
    runtime = detached_runtime()
    runtime.history.config_options = [
        acp_history.ConfigOption("safe", "Safe mode", "boolean", False, None,
                                 [("true", "On"), ("false", "Off")]),
    ]

    class ControlObserver:
        def take(self, method):
            assert method == "session/set_config_option"
            return {"configOptions": [{
                "id": "safe", "name": "Safe mode", "type": "boolean", "currentValue": True,
            }]}

        def raise_if_error(self):
            return None

    class ControlConnection:
        value = None

        async def set_config_option(self, *, config_id, session_id, value):
            self.value = (config_id, session_id, value)

    runtime.observer = ControlObserver()
    runtime.connection = ControlConnection()

    async def apply():
        return await runtime._perform("config", "safe", True)

    assert asyncio.run(apply()) == "applied"
    assert runtime.connection.value == ("safe", "native-id-001", True)
    assert runtime.history.config_options[0].current is True


class ActorThread:
    def __init__(self, actor):
        self.actor = actor

    def is_alive(self):
        return self.actor.available

    def join(self, timeout=None):
        return None


class FakeActor:
    created = []

    def __init__(self, selected, role="root", startup_timeout=acp_runtime.START_TIMEOUT):
        self.target = selected
        self.role = role
        self.startup_timeout = startup_timeout
        self.available = True
        self.busy = False
        self.last_used = time.monotonic()
        self.thread = ActorThread(self)
        self.calls = []
        type(self).created.append(self)

    def request(self, operation, *arguments, timeout=None):
        self.calls.append((operation, *arguments))
        self.last_used = time.monotonic()
        if operation == "discover":
            return [acp_history.Session("native-id-001", "/project", "Root", [])]
        if operation == "snapshot":
            return {
                "status": "active" if self.busy else "unknown",
                "can_send": not self.busy,
                "messages": [],
                "activity": [],
                "timeline": [],
            }
        if operation == "send":
            if self.busy:
                raise DeliveryRejected("active")
            self.busy = True
            self.busy = False
            return "end_turn"
        return "applied"

    def stop_if_idle(self, timeout=3):
        if self.busy:
            return False
        self.available = False
        return True

    def stop(self, timeout=acp_runtime.STOP_TIMEOUT):
        if self.busy:
            self.busy = False
        self.available = False
        return True


def test_runtime_pool_reuses_one_root_actor_for_poll_send_and_cancel():
    FakeActor.created.clear()
    pool = acp_runtime.RuntimePool(runtime_factory=FakeActor)
    selected = target("native-id-001")
    pool.call(selected, "snapshot", None, None)
    pool.call(selected, "send", [{"type": "text", "text": "hello"}])
    pool.call(selected, "cancel")
    assert len(FakeActor.created) == 1
    assert [call[0] for call in FakeActor.created[0].calls] == ["snapshot", "send", "cancel"]
    pool.close()
    assert not FakeActor.created[0].available


def test_runtime_pool_keeps_root_actors_separate():
    FakeActor.created.clear()
    pool = acp_runtime.RuntimePool(runtime_factory=FakeActor)
    pool.call(target("root-one"), "snapshot", None, None)
    pool.call(target("root-two"), "snapshot", None, None)
    assert len(FakeActor.created) == 2
    assert FakeActor.created[0] is not FakeActor.created[1]
    pool.close()


def test_runtime_pool_bounds_hung_native_discovery_and_cancels_its_task(monkeypatch):
    class HangingConnection:
        cancelled = False

        async def list_sessions(self, **kwargs):
            try:
                await asyncio.Event().wait()
            finally:
                self.cancelled = True

    runtime = object.__new__(acp_runtime._SessionRuntime)
    runtime.role = "source"
    runtime.connection = HangingConnection()
    runtime.observer = PromptObserver()
    monkeypatch.setattr(acp_runtime, "DISCOVERY_TIMEOUT", 0.01)

    async def exercise():
        with pytest.raises(asyncio.TimeoutError):
            await runtime._perform("discover")

    asyncio.run(exercise())
    assert runtime.connection.cancelled


def test_runtime_pool_reuses_source_connection_for_catalog_refreshes():
    FakeActor.created.clear()
    pool = acp_runtime.RuntimePool(runtime_factory=FakeActor)
    first = pool.discover(target("seed-one"))
    second = pool.discover(target("seed-two"))
    assert [row.id for row in first] == ["native-id-001"]
    assert [row.id for row in second] == ["native-id-001"]
    assert len(FakeActor.created) == 1 and FakeActor.created[0].role == "source"
    assert [call[0] for call in FakeActor.created[0].calls] == ["discover", "discover"]
    pool.close()


def test_official_sdk_fake_agent_load_poll_prompt_cancel_and_idle_close(monkeypatch):
    monkeypatch.setattr(acp_runtime, "START_TIMEOUT", 5)
    monkeypatch.setattr(acp_runtime, "CALL_TIMEOUT", 10)
    fixture = Path(__file__).with_name("acp_fake_agent.py")
    selected = replace(
        target("fake-root"),
        settings={"command": [sys.executable, str(fixture)], "bridge_backend": "agy"},
    )
    pool = acp_runtime.RuntimePool()

    roots = pool.discover(selected)
    roots_again = pool.discover(selected)
    assert [root.id for root in roots] == ["fake-root", "other-root"]
    assert roots[0].label == roots_again[0].label
    assert len(pool.runtimes) == 1
    source_actor = pool.runtimes[acp_runtime.runtime_key(selected, "source")]
    assert source_actor.role == "source" and source_actor.session is None and source_actor.history is None

    initial = pool.call(selected, "snapshot", None, None)
    assert [message.text for message in initial["messages"]] == ["Loaded history"]
    assert initial["status"] == "unknown"

    sent, failed = [], []

    def send():
        try:
            sent.append(pool.call(selected, "send", [{"type": "text", "text": "Phone message"}]))
        except Exception as error:
            failed.append(error)

    sender = Thread(target=send, daemon=True)
    sender.start()
    deadline = time.monotonic() + 10
    current = initial
    while time.monotonic() < deadline:
        current = pool.call(selected, "snapshot", None, None)
        if current["status"] == "active" and any(
            message.role == "user" and message.text == "Phone message" for message in current["messages"]
        ):
            break
        time.sleep(0.01)
    else:
        pytest.fail("The persistent ACP actor did not publish the live prompt")

    assert pool.call(selected, "cancel") == "applied"
    sender.join(timeout=10)
    assert not sender.is_alive() and failed == [] and sent == ["cancelled"]

    key = acp_runtime.runtime_key(selected)
    actor = pool.runtimes[key]
    actors = list(pool.runtimes.values())
    pool.close()
    assert not actor.thread.is_alive() and all(not item.thread.is_alive() for item in actors)
    assert pool.runtimes == {}


def test_discovery_timeout_cancels_a_hung_sdk_initialize():
    fixture = Path(__file__).with_name("acp_fake_agent.py")
    selected = replace(
        target("fake-root"),
        settings={"command": [sys.executable, str(fixture), "--hang-init"]},
    )
    pool = acp_runtime.RuntimePool(discovery_timeout=0.05)
    with pytest.raises(TimeoutError):
        pool.discover(selected)
    assert pool.runtimes == {} and pool.starting == {}


def test_pool_shutdown_cancels_active_prompt_and_reaps_its_process(monkeypatch):
    monkeypatch.setattr(acp_runtime, "START_TIMEOUT", 5)
    monkeypatch.setattr(acp_runtime, "CALL_TIMEOUT", 10)
    fixture = Path(__file__).with_name("acp_fake_agent.py")
    selected = replace(
        target("fake-root"),
        settings={"command": [sys.executable, str(fixture)], "bridge_backend": "agy"},
    )
    pool = acp_runtime.RuntimePool()
    pool.call(selected, "snapshot", None, None)
    key = acp_runtime.runtime_key(selected)

    sent, failed = [], []

    def send():
        try:
            sent.append(pool.call(selected, "send", [{"type": "text", "text": "shutdown test"}]))
        except Exception as error:
            failed.append(error)

    sender = Thread(target=send, daemon=True)
    sender.start()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        view = pool.call(selected, "snapshot", None, None)
        if view["status"] == "active":
            break
        time.sleep(0.01)
    else:
        pytest.fail("The fake ACP turn did not start")

    actor = pool.runtimes[key]
    pool.close()
    sender.join(timeout=5)
    assert not sender.is_alive() and failed == [] and sent == ["cancelled"]
    assert not actor.thread.is_alive() and pool.runtimes == {}


class PromptObserver:
    def __init__(self):
        self.stop_reason = "end_turn"

    def take(self, method):
        assert method == "session/prompt"
        return {"stopReason": self.stop_reason}

    def raise_if_error(self):
        return None


class PromptConnection:
    def __init__(self, observer):
        self.observer = observer
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.cancelled_session = None

    async def prompt(self, *, session_id, prompt):
        self.started.set()
        await self.cancelled.wait()
        self.observer.stop_reason = "cancelled"
        return SimpleNamespace(stop_reason="cancelled")

    async def cancel(self, *, session_id):
        self.cancelled_session = session_id
        self.cancelled.set()


def detached_runtime():
    runtime = object.__new__(acp_runtime._SessionRuntime)
    runtime.target = target("native-id-001")
    runtime.history = acp_history.History(runtime.target.session_id)
    runtime.session = acp_history.Session(runtime.target.session_id, "/project", "Root", [])
    runtime.capabilities = capabilities()
    runtime.observer = PromptObserver()
    runtime.connection = PromptConnection(runtime.observer)
    runtime._state_lock = Lock()
    runtime._busy = False
    runtime._closing = False
    runtime._last_used = time.monotonic()
    runtime._prompt_task = None
    return runtime


def test_live_prompt_poll_and_cancel_share_one_persistent_connection():
    runtime = detached_runtime()

    async def exercise():
        send = asyncio.create_task(runtime._perform("send", [{"type": "text", "text": "hello"}]))
        await runtime.connection.started.wait()
        view = await runtime._perform("snapshot", None, None)
        assert view["status"] == "active" and not view["can_send"]
        assert await runtime._perform("cancel") == "applied"
        assert await send == "cancelled"
        assert runtime.connection.cancelled_session == runtime.session.id

    asyncio.run(exercise())


def test_duplicate_prompt_is_rejected_while_the_same_runtime_is_busy():
    runtime = detached_runtime()

    async def exercise():
        send = asyncio.create_task(runtime._perform("send", [{"type": "text", "text": "first"}]))
        await runtime.connection.started.wait()
        with pytest.raises(DeliveryRejected):
            await runtime._perform("send", [{"type": "text", "text": "second"}])
        await runtime._perform("cancel")
        await send

    asyncio.run(exercise())

import asyncio
import io
import json
import sys
import tempfile
import uuid
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from agent_inbox import adapters, claude, claude_channel, claude_history, claude_reader
from agent_inbox.media import raster
from agent_inbox.models import Activity, DeliveryRejected, Outgoing, RootInfo, Snapshot, Target, decode_json
from agent_inbox.server import App
from agent_inbox.store import Store


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "state")


def profile_target(tmp_path, profile="one", session_id="connection"):
    config_dir = (tmp_path / ("claude-" + profile)).resolve()
    channels = claude_channel.profile_channels(tmp_path / "state", config_dir)
    return Target(
        "claude-" + profile,
        "claude",
        "Claude",
        session_id,
        "Claude " + profile,
        {"command": str(tmp_path / "bin" / "claude"),
         "config_dir": str(config_dir), "channels": str(channels)},
    )


def live_session(session_id, cwd, *, kind="interactive", status="idle", pid=123, **extra):
    row = {"kind": kind, "sessionId": session_id, "cwd": str(cwd), "status": status, "pid": pid}
    row.update(extra)
    return row


def image_url():
    output = io.BytesIO()
    Image.new("RGB", (3, 2), "#87e1c0").save(output, format="PNG")
    return raster(output.getvalue())


def channel_event(identifier, body="Image attachment", image_count=1):
    return (f'<channel source="agent-inbox" message_id="{identifier}" '
            f'image_count="{image_count}">{body}</channel>')


def sdk_row(session_id, identifier, kind, content, **extra):
    return {
        "type": kind,
        "uuid": identifier,
        "session_id": session_id,
        "message": {"role": "assistant" if kind == "assistant" else "user", "content": content},
        "parent_tool_use_id": None,
        "parent_agent_id": None,
        **extra,
    }


def test_profile_and_session_ids_isolate_channel_sockets(tmp_path):
    session = str(uuid.uuid4())
    profile_a = profile_target(tmp_path, "one", session)
    profile_b = profile_target(tmp_path, "two", session)
    other_session = str(uuid.uuid4())

    assert claude_channel.profile_id(profile_a.settings["config_dir"]) != \
        claude_channel.profile_id(profile_b.settings["config_dir"])
    assert claude_channel.channel_path(profile_a.settings["channels"], session) != \
        claude_channel.channel_path(profile_b.settings["channels"], session)
    assert claude_channel.channel_path(profile_a.settings["channels"], session) != \
        claude_channel.channel_path(profile_a.settings["channels"], other_session)


@pytest.mark.parametrize("wrong_field", ["session_id", "profile"])
def test_channel_ipc_checks_selected_session_and_profile(tmp_path, monkeypatch, wrong_field):
    target = profile_target(tmp_path, "one", str(uuid.uuid4()))
    captured = {}

    class FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def settimeout(self, timeout):
            captured["timeout"] = timeout

        def connect(self, path):
            captured["path"] = path

        def sendall(self, payload):
            captured["request"] = decode_json(payload[:-1])

        def makefile(self, mode):
            response = {
                "session_id": target.session_id,
                "profile": claude_channel.profile_id(target.settings["config_dir"]),
                "ok": True,
                "result": {"ready": True},
            }
            response[wrong_field] = "different-scope"
            return io.BytesIO(json.dumps(response).encode() + b"\n")

    monkeypatch.setattr(claude_channel.socket, "socket", lambda *args: FakeSocket())
    with pytest.raises(RuntimeError):
        claude_channel.channel_call(target, "history")

    assert captured["path"] == str(
        claude_channel.channel_path(target.settings["channels"], target.session_id)
    )
    assert captured["request"]["session_id"] == target.session_id
    assert captured["request"]["profile"] == claude_channel.profile_id(target.settings["config_dir"])


def test_session_listing_is_profile_scoped_and_skips_exited_background_rows(tmp_path, monkeypatch):
    profile_a = profile_target(tmp_path, "one")
    profile_b = profile_target(tmp_path, "two")
    session_a, session_b = str(uuid.uuid4()), str(uuid.uuid4())
    row_a = live_session(session_a, tmp_path / "project-a", status="busy", name="Alpha")
    row_b = live_session(session_b, tmp_path / "project-b", status="idle", name="Beta")
    exited_background = {
        "kind": "background", "sessionId": str(uuid.uuid4()), "cwd": str(tmp_path / "project-a"),
        "state": "working",
    }
    profiles = {
        profile_a.settings["config_dir"]: [row_a, exited_background],
        profile_b.settings["config_dir"]: [row_b],
    }
    calls = []

    def run(argv, *, capture_output, env, timeout):
        calls.append((argv, env["CLAUDE_CONFIG_DIR"], capture_output, timeout))
        return SimpleNamespace(returncode=0, stdout=json.dumps(profiles[env["CLAUDE_CONFIG_DIR"]]).encode())

    monkeypatch.setattr(claude.subprocess, "run", run)

    assert claude.sessions(profile_a) == [row_a]
    assert claude.sessions(profile_b) == [row_b]
    assert calls == [
        ([profile_a.settings["command"], "agents", "--json"], profile_a.settings["config_dir"], True, 8),
        ([profile_b.settings["command"], "agents", "--json"], profile_b.settings["config_dir"], True, 8),
    ]


def test_discovery_uses_native_session_identity_and_skips_sidechains(tmp_path, monkeypatch):
    target = profile_target(tmp_path)
    root_id, sidechain_id = str(uuid.uuid4()), str(uuid.uuid4())
    rows = [
        live_session(root_id, tmp_path / "project", status="waiting", name=None),
        live_session(sidechain_id, tmp_path / "project", status="busy"),
    ]
    reads = []

    def read(seed, row, operation):
        reads.append((seed.settings["config_dir"], row["sessionId"], operation))
        if row["sessionId"] == sidechain_id:
            raise RuntimeError("sidechain has no root metadata")
        return {"info": {"session_id": root_id, "summary": "Existing task", "custom_title": None}}

    monkeypatch.setattr(claude, "sessions", lambda seed: rows)
    monkeypatch.setattr(claude, "read", read)

    assert claude.Claude().discover(target) == [RootInfo(root_id, "Existing task", "input-needed")]
    assert reads == [
        (target.settings["config_dir"], root_id, "info"),
        (target.settings["config_dir"], sidechain_id, "info"),
    ]


@dataclass
class FakeInfo:
    session_id: str
    summary: str = "Existing task"
    file_size: int = 64
    custom_title: str | None = None
    first_prompt: str | None = "Prompt"
    git_branch: str | None = None
    cwd: str | None = None
    tag: str | None = None
    created_at: int | None = None


@dataclass
class FakeMessage:
    type: str
    uuid: str
    session_id: str
    message: dict
    parent_tool_use_id: str | None = None
    parent_agent_id: str | None = None


def test_sdk_reader_is_read_only_and_rejects_a_different_session(tmp_path, monkeypatch):
    session_id = str(uuid.uuid4())
    directory = str(tmp_path / "project")
    calls = []
    info = FakeInfo(session_id, cwd=directory)
    message = FakeMessage(session_id=session_id, uuid="message-1", type="user",
                          message={"role": "user", "content": [{"type": "text", "text": "hello"}]})

    def get_info(identifier, *, directory):
        calls.append(("info", identifier, directory))
        return info

    def get_messages(identifier, *, directory):
        calls.append(("messages", identifier, directory))
        return [message]

    def list_subagents(identifier, *, directory):
        calls.append(("subagents", identifier, directory))
        return ["agent-child"]

    monkeypatch.setattr(claude_reader, "get_session_info", get_info)
    monkeypatch.setattr(claude_reader, "get_session_messages", get_messages)
    monkeypatch.setattr(claude_reader, "list_subagents", list_subagents)

    result = claude_reader.read({"session": session_id, "directory": directory, "operation": "history"})
    assert result["info"]["session_id"] == session_id
    assert result["messages"] == [message.__dict__]
    assert result["children"] == ["agent-child"]
    assert calls == [
        ("info", session_id, directory),
        ("messages", session_id, directory),
        ("subagents", session_id, directory),
    ]

    wrong = str(uuid.uuid4())
    monkeypatch.setattr(claude_reader, "get_session_info", lambda _id, *, directory: FakeInfo(wrong))
    with pytest.raises(ValueError, match="existing main sessions"):
        claude_reader.read({"session": session_id, "directory": directory, "operation": "info"})


def test_sdk_reader_subprocess_is_pinned_to_selected_profile(tmp_path, monkeypatch):
    target = profile_target(tmp_path, "two")
    session_id = str(uuid.uuid4())
    live = live_session(session_id, tmp_path / "project", status="busy")
    captured = {}

    def run(argv, *, input, capture_output, timeout, env):
        captured.update(argv=argv, request=decode_json(input), env=env, timeout=timeout)
        response = {"info": {"session_id": session_id}, "messages": [], "children": []}
        return SimpleNamespace(returncode=0, stdout=json.dumps(response).encode())

    monkeypatch.setattr(claude.subprocess, "run", run)
    result = claude.read(target, live, "history")

    assert result["info"]["session_id"] == session_id
    assert captured["argv"] == [claude.sys.executable, "-m", "agent_inbox.claude_reader"]
    assert captured["request"] == {
        "session": session_id, "directory": live["cwd"], "operation": "history",
    }
    assert captured["env"]["CLAUDE_CONFIG_DIR"] == target.settings["config_dir"]
    assert captured["timeout"] == 10


def test_send_routes_only_to_the_selected_live_session(tmp_path, monkeypatch):
    target = profile_target(tmp_path, "one", str(uuid.uuid4()))
    row = live_session(target.session_id, tmp_path / "project", status="busy")
    calls = []
    message = Outgoing(str(uuid.uuid4()), "Check this image", [])

    monkeypatch.setattr(claude, "sessions", lambda selected: [row]
                        if selected.settings["config_dir"] == target.settings["config_dir"] else [])

    def channel_call(selected, method, payload=None):
        calls.append((selected.settings["config_dir"], selected.session_id, method, payload))
        return {"id": message.id, "status": "forwarded"}

    monkeypatch.setattr(claude, "channel_call", channel_call)
    assert claude.Claude().send(target, message) == "forwarded"
    assert calls == [(target.settings["config_dir"], target.session_id, "send",
                      {"id": message.id, "text": message.text, "images": []})]

    wrong_root = replace(target, session_id=str(uuid.uuid4()))
    with pytest.raises(DeliveryRejected):
        claude.Claude().send(wrong_root, message)
    assert len(calls) == 1


def test_ambiguous_claude_dispatch_reuses_receipt_without_resending(tmp_path, monkeypatch):
    store = Store(tmp_path / "state")
    seed = store.register(profile_target(tmp_path, "dispatch"))
    app = App(store)
    provider = adapters.ADAPTERS["claude"]
    session_id = str(uuid.uuid4())
    monkeypatch.setattr(provider, "discover", lambda _seed: [RootInfo(session_id, "Live root", "active")])
    monkeypatch.setattr(provider, "snapshot", lambda *_args, **_kwargs: Snapshot("active", True, []))
    dispatched = []

    def uncertain(target, message):
        dispatched.append((target.session_id, message.id))
        raise RuntimeError("write may have reached the channel")

    monkeypatch.setattr(provider, "send", uncertain)
    row = next(row for row in app.catalog.listing()["roots"] if row["label"] == "Live root")
    data = {"id": str(uuid.uuid4()), "target": row["id"], "text": "one message"}

    assert app.send(data)["status"] == "unknown"
    assert app.send(data)["status"] == "unknown"
    assert dispatched == [(session_id, data["id"])]
    assert store.targets() == [seed]


def test_relay_deduplicates_concurrent_same_id_and_rejects_changed_payload():
    identifier = str(uuid.uuid4())
    notifications = []

    async def notify(params):
        notifications.append(params)

    relay = claude_channel.Relay(identifier, notify)
    relay.ready = True
    payload = {"id": str(uuid.uuid4()), "text": "hello", "images": []}

    async def submit_twice():
        return await asyncio.gather(relay.send(payload), relay.send(payload))

    assert asyncio.run(submit_twice()) == [
        {"id": payload["id"], "status": "forwarded"},
        {"id": payload["id"], "status": "forwarded"},
    ]
    assert len(notifications) == 1
    assert relay.history()["messages"] == [
        {"id": payload["id"], "text": "hello", "images": [], "status": "forwarded"}
    ]

    changed = {**payload, "text": "different"}
    with pytest.raises(ValueError, match="reused"):
        asyncio.run(relay.send(changed))
    assert len(notifications) == 1


def test_relay_preserves_unconsumed_images_and_unknown_notification_is_not_replayed():
    url = image_url()
    identifier = str(uuid.uuid4())
    notifications = []
    payload = {"id": str(uuid.uuid4()), "text": "", "images": [url]}

    async def notify_then_fail(params):
        notifications.append(params)
        raise RuntimeError("transport failed after write")

    relay = claude_channel.Relay(identifier, notify_then_fail)
    relay.ready = True

    async def fail_twice():
        with pytest.raises(RuntimeError):
            await relay.send(payload)
        with pytest.raises(RuntimeError, match="unknown"):
            await relay.send(payload)

    asyncio.run(fail_twice())
    assert len(notifications) == 1
    assert relay.messages[payload["id"]]["status"] == "unknown"
    assert relay.messages[payload["id"]]["images"] == [url]
    assert relay.history()["messages"][0]["images"] == [url]


def test_relay_never_evicts_unconsumed_image_at_message_capacity():
    url = image_url()
    identifier = str(uuid.uuid4())
    notifications = []

    async def notify(params):
        notifications.append(params)

    relay = claude_channel.Relay(identifier, notify)
    relay.ready = True
    image_message = {"id": str(uuid.uuid4()), "text": "", "images": [url]}

    async def fill():
        await relay.send(image_message)
        for _ in range(99):
            await relay.send({"id": str(uuid.uuid4()), "text": "plain", "images": []})
        with pytest.raises(ValueError, match="unconsumed"):
            await relay.send({"id": str(uuid.uuid4()), "text": "overflow", "images": []})

    asyncio.run(fill())
    assert len(relay.messages) == 100
    assert relay.messages[image_message["id"]]["images"] == [url]
    assert len(notifications) == 100


def test_history_projection_correlates_channel_images_and_filters_subagent_content():
    session_id, message_id = str(uuid.uuid4()), str(uuid.uuid4())
    url = image_url()
    encoded = url.partition(",")[2]
    outgoing = [{"id": message_id, "text": "What is in this image?", "images": [url], "status": "forwarded"}]
    rows = [
        sdk_row(session_id, "user-1", "user", [{"type": "text", "text": "Review this."}]),
        sdk_row(session_id, "assistant-1", "assistant", [
            {"type": "text", "text": "I will inspect it."},
            {"type": "tool_use", "id": "tool-1", "name": "Read", "input": {"path": "secret"}},
        ]),
        sdk_row(session_id, "child", "assistant", [
            {"type": "text", "text": "private child output"},
        ], parent_tool_use_id="tool-1"),
        sdk_row(session_id, "channel-1", "user", [
            {"type": "text", "text": channel_event(message_id)},
        ]),
        sdk_row(session_id, "tool-result", "user", [
            {"type": "tool_result", "tool_use_id": "tool-1", "content": [
                {"type": "text", "text": "private tool output"},
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": encoded}},
            ]},
        ]),
    ]

    messages, activity, timeline = claude_history.decode(rows, session_id, outgoing)
    assert [message.id for message in messages] == [
        "claude:user-1", "claude:assistant-1", "channel:" + message_id, "claude:tool-result",
    ]
    assert messages[2].text == "What is in this image?"
    assert messages[2].images == [url]
    assert messages[3].role == "assistant" and messages[3].images == [url]
    assert activity == [Activity("activity:claude:tool-1", "Read", "observed")]
    encoded = json.dumps([asdict(message) for message in messages])
    assert "private child output" not in encoded
    assert "private tool output" not in encoded
    assert "secret" not in encoded
    assert timeline == ["claude:user-1", "activity:claude:tool-1", "claude:assistant-1",
                       "channel:" + message_id, "claude:tool-result"]


def test_history_projection_strips_native_wrapper_without_exposing_foreign_sessions():
    session_id, message_id = str(uuid.uuid4()), str(uuid.uuid4())
    event = sdk_row(session_id, "channel-1", "user", [
        {"type": "text", "text": channel_event(message_id, "plain reply", image_count=0)},
    ])
    messages, _, _ = claude_history.decode([event], session_id, append_outgoing=False)
    assert messages[0].text == "plain reply"
    assert "message_id" not in messages[0].text
    assert messages[0].id == "claude:channel-1"

    with pytest.raises(ValueError, match="another session"):
        claude_history.decode([event], str(uuid.uuid4()))


def test_older_history_page_still_correlates_relay_message(monkeypatch, tmp_path):
    session_id, message_id = str(uuid.uuid4()), str(uuid.uuid4())
    target = profile_target(tmp_path, "one", session_id)
    row = live_session(session_id, tmp_path / "project", status="idle")
    url = image_url()
    event = sdk_row(session_id, "channel-1", "user", [
        {"type": "text", "text": channel_event(message_id)},
    ])
    monkeypatch.setattr(claude, "sessions", lambda _target: [row])
    monkeypatch.setattr(claude, "read", lambda *_args: {"info": {}, "messages": [event], "children": []})
    monkeypatch.setattr(claude, "channel_call", lambda *_args: {
        "ready": True, "messages": [{"id": message_id, "text": "original text", "images": [url],
                                      "status": "forwarded"}],
    })

    snapshot = claude.Claude().snapshot(
        target, cursor=claude_history.encode_cursor(1, "channel-1"),
    )
    assert snapshot.messages[0].id == "channel:" + message_id
    assert snapshot.messages[0].text == "original text"
    assert snapshot.messages[0].images == [url]


@pytest.fixture
def short_state_path():
    with tempfile.TemporaryDirectory(prefix="inbox-") as directory:
        yield Path(directory)


def test_native_mcp_channel_handshake_and_attachment_tool(short_state_path):
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    state, session = short_state_path / "state", str(uuid.uuid4())
    profile = short_state_path / "profile"
    selected = profile_target(short_state_path, session_id=session)
    selected = replace(selected, settings={**selected.settings, "config_dir": str(profile),
                                          "channels": str(claude_channel.profile_channels(state, profile))})
    message = {"id": str(uuid.uuid4()), "text": "", "images": [image_url()]}

    async def check():
        parameters = StdioServerParameters(command=sys.executable, args=[
            "-m", "agent_inbox.cli", "--state", str(state), "claude-channel",
            "--session", session, "--config-dir", str(profile)])
        async with stdio_client(parameters) as (incoming, outgoing):
            async with ClientSession(incoming, outgoing, read_timeout_seconds=5) as client:
                initialized = await client.initialize()
                assert "claude/channel" in initialized.capabilities.experimental
                assert [tool.name for tool in (await client.list_tools()).tools] == ["image"]
                receipt = await asyncio.to_thread(claude_channel.channel_call, selected, "send", message)
                assert receipt == {"id": message["id"], "status": "forwarded"}
                viewed = await client.call_tool("image", {"message_id": message["id"], "index": 0})
                assert not viewed.is_error and viewed.content[0].type == "image"
                assert viewed.content[0].data == message["images"][0].partition(",")[2]
                foreign = replace(selected, settings={**selected.settings,
                                                       "config_dir": str(profile / "other")})
                with pytest.raises(RuntimeError):
                    await asyncio.to_thread(claude_channel.channel_call, foreign, "history")

    asyncio.run(asyncio.wait_for(check(), timeout=15))
    assert not claude_channel.channel_path(selected.settings["channels"], session).exists()

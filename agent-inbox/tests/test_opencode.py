import base64
import io
import json
from dataclasses import replace
from urllib.parse import parse_qs, urlsplit

import pytest
from PIL import Image

from agent_inbox import opencode, opencode_history
from agent_inbox.media import raster
from agent_inbox.models import DeliveryRejected, Outgoing, Target
from agent_inbox.opencode_http import ApiRejected, Connection


def target():
    return Target("root", "opencode", "OpenCode", "ses_root", "Root", {"service": "/test/service.json"})


def root(identifier="ses_root", **kwargs):
    return {"id": identifier, "time": {"created": 1, "updated": 2}, "title": "Root",
            "location": {"directory": "/project"}, **kwargs}


def native_page(rows, previous="newer", following=None):
    return {"data": rows, "cursor": {"previous": previous, "next": following}}


def assistant(body="Reply"):
    return {"id": "msg_assistant", "type": "assistant", "content": [
        {"type": "reasoning", "text": "private reasoning"}, {"type": "text", "text": body},
    ]}


class NativeApi:
    def __init__(self):
        self.calls, self.items, self.metadata = [], [assistant()], root()
        self.error = None

    def call(self, method, path, body=None):
        self.calls.append((method, path, body))
        parsed = urlsplit(path)
        if method == "POST":
            if self.error:
                raise self.error
            if parsed.path.endswith("/prompt"):
                return {"data": {"id": body["id"], "sessionID": "ses_root", "type": "user",
                                 "delivery": "steer", "payload": {"text": body["text"]}}}
            return None
        if parsed.path == "/api/session/active":
            return {"data": {"ses_root": {"type": "running"}}}
        if parsed.path == "/api/session":
            return native_page([self.metadata], following=None)
        if parsed.path == "/api/session/ses_root":
            return {"data": self.metadata}
        if parsed.path.endswith("/message/msg_assistant"):
            return {"data": self.items[0]}
        if parsed.path.endswith("/message"):
            return native_page(self.items)
        if parsed.path == "/api/model":
            return {"data": [{"id": "model", "providerID": "provider", "name": "Model",
                              "enabled": True, "variants": [{"id": "high"}]}]}
        if parsed.path == "/api/agent":
            return {"data": [{"name": "build", "mode": "primary"},
                              {"name": "worker", "mode": "subagent"}]}
        if parsed.path == "/api/command":
            return {"data": [{"name": "check", "description": "Check project"}]}
        raise AssertionError((method, path))


@pytest.fixture
def api(monkeypatch):
    api = NativeApi()
    monkeypatch.setattr(opencode, "Connection", lambda selected: api)
    return api


def test_discovery_keeps_existing_root_identity_and_omits_archived_roots(api):
    result = opencode.OpenCode().discover(target())
    assert [(row.session_id, row.status) for row in result] == [("ses_root", "active")]
    api.metadata["time"]["archived"] = 3
    assert opencode.OpenCode().discover(target()) == []
    with pytest.raises(ValueError):
        opencode.OpenCode().snapshot(target())


def test_saved_discovery_does_not_claim_idle_native_history_is_a_live_terminal(api):
    native = api.call

    def stopped(method, path, body=None):
        return {"data": {}} if path == "/api/session/active" else native(method, path, body)

    api.call = stopped
    roots = opencode.OpenCode().discover(target())
    assert roots[0].saved and roots[0].status == "idle"
    api.metadata = root(parentID="ses_parent")
    with pytest.raises(ValueError):
        opencode.OpenCode().snapshot(target())


def test_history_updates_streaming_record_without_exposing_reasoning(api):
    provider = opencode.OpenCode()
    first = provider.snapshot(target())
    assert [row.text for row in first.messages] == ["Reply"]
    api.items = []
    original_call = api.call

    def changed(method, path, body=None):
        if path.endswith("/message/msg_assistant"):
            return {"data": assistant("Reply continued")}
        return original_call(method, path, body)

    api.call = changed
    second = provider.snapshot(target(), since=first.newer_cursor)
    assert [row.text for row in second.messages] == ["Reply continued"]
    assert second.newer_cursor == first.newer_cursor
    assert any(parse_qs(urlsplit(path).query).get("cursor") == ["newer"] for _, path, _ in api.calls)


def test_image_input_uses_native_admission_with_stable_root_and_id(api):
    raw = io.BytesIO()
    Image.new("RGB", (4, 4)).save(raw, "PNG")
    image = raster(raw.getvalue())
    message = Outgoing("62c72a25-46ab-48ac-8aac-250cb6e1882d", "", [image])
    assert opencode.OpenCode().send(target(), message) == "queued"
    method, path, payload = api.calls[-1]
    assert (method, path) == ("POST", "/api/session/ses_root/prompt")
    assert payload == {"id": "msg_62c72a2546ab48ac8aac250cb6e1882d", "text": "", "delivery": "steer",
                       "files": [{"uri": image}]}
    api.error = ApiRejected(409)
    with pytest.raises(DeliveryRejected):
        opencode.OpenCode().send(target(), message)
    assert len([call for call in api.calls if call[0] == "POST"]) == 2
    api.error = TimeoutError()
    with pytest.raises(TimeoutError):
        opencode.OpenCode().send(target(), message)


def test_native_attachments_render_only_valid_embedded_images():
    raw = io.BytesIO()
    Image.new("RGB", (5, 5)).save(raw, "PNG")
    encoded = base64.b64encode(raw.getvalue()).decode()
    rows = [{"id": "msg_user", "type": "user", "text": "Photo",
             "files": [{"data": encoded, "mime": "image/png", "source": {"type": "inline"}}]},
            assistant()]
    rows[1]["content"].append({"type": "tool", "state": {"status": "completed", "content": [
        {"type": "file", "uri": "data:image/png;base64," + encoded, "mime": "image/png"},
        {"type": "text", "text": "private tool output"},
    ]}})
    result = opencode_history.messages(rows)
    assert result[0].images == result[1].images == [raster(raw.getvalue())]
    rows[0]["files"][0] = {"uri": "file:///etc/passwd", "mime": "image/png"}
    result = opencode_history.messages(rows)
    assert result[0].images is None and "unavailable" in result[0].text


def test_native_controls_discovered_per_location_and_validated_before_mutation(api):
    provider = opencode.OpenCode()
    controls = provider.commands(target())
    assert [c.id for c in controls.controls] == ["model", "agent", "interrupt", "slash:check"]
    assert controls.controls[1].choices[0].value == "build"
    assert len(controls.controls[1].choices) == 1
    option = controls.controls[0].choices[1].value
    assert provider.execute(target(), "model", option) == "applied"
    assert api.calls[-1] == ("POST", "/api/session/ses_root/model",
                             {"model": {"id": "model", "providerID": "provider", "variant": "high"}})
    with pytest.raises(DeliveryRejected):
        provider.execute(target(), "model", "invented model")
    with pytest.raises(DeliveryRejected):
        provider.execute(target(), "slash:unknown", "argument")
    assert provider.execute(target(), "slash:check", "literal $(value)") == "applied"
    assert api.calls[-1][2] == {"command": "check", "text": "literal $(value)"}


@pytest.mark.parametrize("url", ["http://example.test:123", "http://127.0.0.1:123/path",
                                 "https://127.0.0.1:123", "http://user@127.0.0.1:123"])
def test_connection_refuses_nonlocal_or_ambiguous_service_urls(tmp_path, url):
    path = tmp_path / "service.json"
    path.write_text(json.dumps({"url": url, "password": "fixture", "version": "2.0.3",
                                "pid": 123, "id": "x"}))
    selected = replace(target(), settings={"service": str(path)})
    with pytest.raises(ValueError):
        Connection(selected)


def test_history_cursor_and_native_identity_must_remain_unambiguous(api):
    page = opencode.OpenCode().snapshot(target())
    with pytest.raises(ValueError):
        opencode_history.decode_anchor('{"cursor":"a","cursor":"b","last":"msg_a"}')
    api.metadata = root("ses_other")
    with pytest.raises(ValueError):
        opencode.OpenCode().snapshot(target(), since=page.newer_cursor)
    with pytest.raises(ValueError):
        opencode.session_path("ses_root/../../other")


def test_tool_events_keep_native_interleaving_and_update_stable_ids(api):
    api.items = [{"id": "msg_assistant", "type": "assistant", "content": [
        {"type": "text", "text": "Before"},
        {"type": "tool", "id": "call_one", "name": "bash", "time": {"created": 100, "ran": 120},
         "state": {"status": "running", "input": {"command": "private argument"}, "metadata": {}}},
        {"type": "text", "text": "After"},
    ]}]
    snapshot = opencode.OpenCode().snapshot(target())
    assert snapshot.timeline == ["msg_assistant", "activity:msg_assistant:call_one",
                                 "msg_assistant:block:2"]
    assert [m.text for m in snapshot.messages] == ["Before", "After"]
    assert snapshot.activity[0].label == "bash" and snapshot.activity[0].status == "running"
    tool = api.items[0]["content"][1]
    tool.update(time={"created": 100, "ran": 120, "completed": 200},
                state={"status": "completed", "input": {}, "content": []})
    updated = opencode.OpenCode().snapshot(target())
    assert updated.timeline == snapshot.timeline
    assert updated.activity[0].duration_ms == 80 and updated.activity[0].status == "completed"

import concurrent.futures
import contextlib
import http.client
import io
import json
import stat
import threading
import uuid
from dataclasses import replace

import pytest
from PIL import Image

from agent_inbox import adapters, codex, codex_history
from agent_inbox.catalog import Catalog
from agent_inbox.commands import Choice, Command, Commands
from agent_inbox.context import SessionContext
from agent_inbox.forms import FormField, Forms, QuestionForm
from agent_inbox.media import raster
from agent_inbox.models import (
    DeliveryRejected,
    Message,
    Outgoing,
    PairingError,
    RootInfo,
    Snapshot,
    Target,
    decode_json,
    https_url,
)
from agent_inbox.presentation import render_snapshot
from agent_inbox.server import App, Server
from agent_inbox.store import Store


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "state")


def target(identifier="first"):
    return Target(identifier, "fixture", "Fixture", identifier, "Root " + identifier, {})


class FixtureAdapter:
    def __init__(self):
        self.sent = []
        self.ready = True
        self.error = False

    def discover(self, seed):
        return None

    def snapshot(self, selected, cursor=None, since=None):
        return Snapshot("idle", self.ready, [Message("m", "assistant", "Hello from " + selected.id)])

    def send(self, selected, message):
        self.sent.append((selected.session_id, message.text))
        if self.error:
            raise TimeoutError("private diagnostic must not reach HTTP")
        return "queued"


@pytest.fixture
def provider(monkeypatch):
    provider = FixtureAdapter()
    monkeypatch.setitem(adapters.ADAPTERS, "fixture", provider)
    return provider


def submission(root="first", body="ordinary message"):
    return {"id": str(uuid.uuid4()), "target": root, "text": body}


def test_pairing_is_private_one_use_and_revocable(store):
    code = store.pair_code()
    device, token = store.pair(code, "Phone")
    assert store.authenticated(token)
    assert token.encode() not in store.path.read_bytes()
    assert code.encode() not in store.path.read_bytes()
    with pytest.raises(PairingError):
        store.pair(code, "Other phone")
    assert stat.S_IMODE(store.home.stat().st_mode) == 0o700
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    store.revoke(device)
    assert not store.authenticated(token)


def test_pairing_limit_and_expiry(store, monkeypatch):
    code = store.pair_code()
    for _ in range(8):
        with pytest.raises(PairingError):
            store.pair("incorrect", "Phone")
    with pytest.raises(PairingError):
        store.pair(code, "Phone")
    monkeypatch.setattr("agent_inbox.store.time.time", lambda: 1000)
    code = store.pair_code()
    monkeypatch.setattr("agent_inbox.store.time.time", lambda: 1301)
    with pytest.raises(PairingError):
        store.pair(code, "Phone")
    code = store.pair_code()
    _, token = store.pair(code, "Phone")
    monkeypatch.setattr("agent_inbox.store.time.time", lambda: 1301 + 2592001)
    assert not store.authenticated(token)


def test_registry_is_idempotent_and_rejects_id_collision(store):
    original = store.register(target())
    assert store.register(replace(original, id="second")) == original
    with pytest.raises(ValueError):
        store.register(replace(original, session_id="another-session"))
    store.remove(original.id)
    assert store.targets() == []


def test_routing_replay_and_concurrent_delivery(store, provider):
    for root in ("first", "second"):
        store.register(target(root))
    app, data = App(store), submission("second")
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: app.send(data), range(6)))
    assert all(r["status"] in ("queued", "sending") for r in results)
    assert provider.sent == [("second", data["text"])]
    assert app.send(data)["status"] == "queued"
    for changed in ({**data, "target": "first"}, {**data, "text": "different"}):
        with pytest.raises(ValueError):
            app.send(changed)


def test_unknown_delivery_is_not_repeated_and_crashes_recover(store, provider):
    store.register(target())
    provider.error = True
    app, data = App(store), submission()
    assert app.send(data)["status"] == "unknown"
    assert app.send(data)["status"] == "unknown"
    assert len(provider.sent) == 1
    interrupted = submission()
    store.reserve(interrupted["id"], interrupted["target"], interrupted["text"])
    store.recover()
    assert app.send(interrupted)["status"] == "unknown"
    assert len(provider.sent) == 1
    provider.ready = False
    assert app.send(submission())["status"] == "failed"
    assert len(provider.sent) == 1


def test_image_submission_is_bound_to_root_and_receipt(store, provider):
    store.register(target())
    raw = io.BytesIO()
    Image.new("RGB", (12, 8)).save(raw, format="PNG")
    url = raster(raw.getvalue())
    app, data = App(store), {**submission(body=""), "images": [url]}
    assert app.send(data)["status"] == "queued"
    assert app.send(data)["status"] == "queued"
    assert len(provider.sent) == 1
    with pytest.raises(ValueError):
        app.send({**data, "images": [url, url]})
    for key in ("path", "files"):
        with pytest.raises(ValueError):
            app.send({**submission(), key: "/etc/passwd"})
    assert url.encode() not in store.path.read_bytes()


@pytest.mark.parametrize("raw", ['{"id":1,"id":2}', '{"nested":{"a":1,"a":2}}', '{"n":NaN}', '{"n":1e999}'])
def test_strict_json(raw):
    with pytest.raises(ValueError):
        decode_json(raw)


@pytest.mark.parametrize("url", ["http://example.test", "https://user:pass@example.test", "javascript:bad",
                                 "https://example.test\n/", "https://example.test:99999"])
def test_native_links_reject_unsafe_urls(url):
    with pytest.raises(ValueError):
        https_url(url)


@pytest.mark.parametrize("harness", ["Claude", "Antigravity", "OpenCode"])
def test_other_harnesses_open_native_chat_and_never_dispatch_inbox_input(harness, store):
    selected = Target("native-root", "native", harness, "existing-root", "Native root",
                      {"url": "https://example.test/existing/root"})
    store.register(selected)
    app = App(store)
    assert app.catalog.listing()["roots"][0]["status"] == "native"
    snapshot = adapters.adapter(selected).snapshot(selected)
    assert snapshot.native_url == selected.settings["url"] and not snapshot.can_send
    assert app.send(submission("native-root"))["status"] == "failed"


@pytest.fixture
def http_server(store, provider):
    store.register(target())
    store.register(target("second"))
    server = Server(App(store), 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()
    thread.join()


def request(server, method, path, data=None, cookie=None, origin=None, host=None):
    port = server.server_address[1]
    headers = {"Host": host or f"127.0.0.1:{port}"}
    if method == "POST":
        headers.update({"Origin": origin or f"http://127.0.0.1:{port}", "Content-Type": "application/json"})
    if cookie:
        headers["Cookie"] = cookie
    if origin:
        headers["Origin"] = origin
    body = json.dumps(data) if data is not None else None
    with contextlib.closing(http.client.HTTPConnection("127.0.0.1", port, timeout=3)) as connection:
        connection.request(method, path, body, headers)
        response = connection.getresponse()
        raw = response.read()
        result = raw if response.getheader("Content-Type", "").startswith("image/") else json.loads(raw)
        return response.status, dict(response.getheaders()), result


def test_http_pair_auth_origin_and_isolation(http_server, store, provider):
    server = http_server
    assert request(server, "GET", "/api/roots")[0] == 401
    code = store.pair_code()
    assert request(server, "POST", "/api/pair", {"code": code, "name": "Phone"},
                   origin="https://attacker.test")[0] == 403
    status, headers, result = request(server, "POST", "/api/pair", {"code": code, "name": "Phone"})
    assert status == 200
    assert set(result) == {"device"}
    assert "HttpOnly" in headers["Set-Cookie"] and "SameSite=Strict" in headers["Set-Cookie"]
    cookie = headers["Set-Cookie"].split(";")[0]
    status, _, result = request(server, "GET", "/api/roots", cookie=cookie)
    assert status == 200
    assert all(set(root) == {"id", "harness", "label", "status"} for root in result["roots"])
    view = request(server, "GET", "/api/view?id=second", cookie=cookie)[2]
    assert view["messages"][0]["text"].endswith("second")
    assert request(server, "GET", "/api/roots", cookie=cookie, host="attacker.test")[0] == 403
    assert request(server, "POST", "/api/send", submission(), cookie=cookie,
                   origin="https://attacker.test")[0] == 403
    assert provider.sent == []
    data = submission("second")
    assert request(server, "POST", "/api/send", data, cookie)[2]["status"] == "queued"
    assert request(server, "POST", "/api/send", data, cookie)[2]["status"] == "queued"
    assert provider.sent == [("second", data["text"])]
    assert request(server, "GET", "/api/view?id=first&id=second", cookie=cookie)[0] == 400
    store.revoke(store.devices()[0][0])
    assert request(server, "GET", "/api/roots", cookie=cookie)[0] == 401


def test_http_error_does_not_disclose_diagnostics(http_server, store, provider, monkeypatch):
    _, token = store.pair(store.pair_code(), "Phone")

    def unavailable(*args, **kwargs):
        raise RuntimeError("a private token or path")

    monkeypatch.setattr(provider, "snapshot", unavailable)
    status, _, data = request(http_server, "GET", "/api/view?id=first", cookie="inbox=" + token)
    assert status == 503
    assert "private" not in json.dumps(data)


def test_http_native_controls_and_answers_are_authenticated_and_root_scoped(
        http_server, store, provider, monkeypatch):
    _, token = store.pair(store.pair_code(), "Phone")
    cookie, calls = "inbox=" + token, []
    monkeypatch.setattr(provider, "commands", lambda selected: Commands([
        Command("model", "Model", "select", [Choice(selected.id, selected.id)])]), raising=False)
    monkeypatch.setattr(provider, "forms", lambda selected: Forms([
        QuestionForm(selected.id, "Choose", [FormField("yes", "Continue", "boolean", True)])]), raising=False)
    monkeypatch.setattr(provider, "context", lambda selected: SessionContext(
        notices=[selected.id]), raising=False)

    def execute(selected, name, value):
        calls.append((selected.id, name, value))
        return "applied"

    def answer(selected, identifier, values, cancel):
        calls.append((selected.id, identifier, values, cancel))
        return "applied"

    monkeypatch.setattr(provider, "execute", execute, raising=False)
    monkeypatch.setattr(provider, "answer", answer, raising=False)
    for path in ("commands", "context", "forms"):
        assert request(http_server, "GET", f"/api/{path}?id=second")[0] == 401
        assert request(http_server, "GET", f"/api/{path}?id=second", cookie=cookie)[0] == 200
        assert request(http_server, "GET", f"/api/{path}?id=first&id=second", cookie=cookie)[0] == 400
    command = {"id": str(uuid.uuid4()), "target": "second", "command": "model", "value": "second"}
    assert request(http_server, "POST", "/api/command", command, cookie,
                   origin="https://attacker.test")[0] == 403
    assert not calls
    assert request(http_server, "POST", "/api/command", command, cookie)[2]["status"] == "applied"
    reply = {"id": str(uuid.uuid4()), "target": "first", "form": "first", "answer": {"yes": False}}
    assert request(http_server, "POST", "/api/answer", reply, cookie)[2]["status"] == "applied"
    assert calls == [("second", "model", "second"), ("first", "first", {"yes": False}, False)]
    assert request(http_server, "GET", "/assets/../server.py", cookie=cookie)[0] == 404


def test_inline_images_need_pairing_without_resending_in_history(http_server, store, provider, monkeypatch):
    raw = io.BytesIO()
    Image.new("RGB", (12, 8)).save(raw, format="PNG")
    url = raster(raw.getvalue())
    monkeypatch.setattr(provider, "snapshot", lambda *args: Snapshot(
        "idle", True, [Message("image", "assistant", "", images=[url])],
    ))
    device, token = store.pair(store.pair_code(), "Phone")
    cookie = "inbox=" + token
    view = request(http_server, "GET", "/api/view?id=first", cookie=cookie)[2]
    path = view["messages"][0]["images"][0]
    assert path.startswith("/api/image?id=") and "base64" not in json.dumps(view)
    assert request(http_server, "GET", path)[0] == 401
    status, headers, body = request(http_server, "GET", path, cookie=cookie)
    assert status == 200 and headers["Content-Type"] == "image/png"
    assert body == raw.getvalue()
    assert request(http_server, "GET", "/api/image?id=" + "0" * 64, cookie=cookie)[0] == 404
    store.revoke(device)
    assert request(http_server, "GET", path, cookie=cookie)[0] == 401


class FakeRpc:
    def __init__(self, value):
        self.value = value

    def call(self, method, params):
        assert method == "thread/read"
        return {"thread": self.value}


def codex_root():
    return {"id": "root-id", "sessionId": "root-id", "parentThreadId": None, "canAcceptDirectInput": True,
            "status": {"type": "idle"}}


def codex_target():
    return Target("t", "codex", "Codex", "root-id", "Root",
                  {"socket": "/tmp/test-codex.sock", "command": ["/usr/bin/codex"]})


@pytest.mark.parametrize("change", [{"parentThreadId": "parent"}, {"id": "other"},
                                    {"sessionId": "parent-root"},
                                    {"canAcceptDirectInput": 1}, {"status": {"type": "invented"}}])
def test_codex_rejects_workers_wrong_roots_and_malformed_metadata(change):
    with pytest.raises(ValueError):
        codex.root(FakeRpc({**codex_root(), **change}), codex_target())
    incomplete = codex_root()
    del incomplete["parentThreadId"]
    with pytest.raises(ValueError):
        codex.root(FakeRpc(incomplete), codex_target())


def test_codex_only_exposes_chat_and_preserves_cursor():
    def row(kind, **kwargs):
        return {"turnId": "turn", "item": {"id": kind, "type": kind, **kwargs}}

    page = {"nextCursor": "older", "backwardsCursor": "newer", "data": [row("agentMessage", text="Reply"),
            row("reasoning", text="private reasoning"), row("commandExecution", text="private tool output"),
            row("userMessage", content=[{"type": "text", "text": "Question"}])]}
    decoded = codex_history.decode_page(page)
    messages, cursor = decoded.messages, decoded.older
    assert [m.text for m in messages] == ["Question", "Reply"]
    assert [m.role for m in messages] == ["user", "assistant"]
    assert cursor == "older"
    page["data"] = [row("userMessage", content=["malformed"])]
    with pytest.raises(ValueError):
        codex_history.decode_page(page)


def test_codex_queues_exact_selected_existing_root(monkeypatch):
    calls = []

    class QueueRpc:
        def call(self, method, params):
            calls.append((method, params))
            if method == "thread/read":
                return {"thread": codex_root()}
            assert method == "thread/queue/add"
            return {"queuedSubmission": {"id": "q", "clientUserMessageId": params["clientUserMessageId"],
                                         "input": params["input"]}}

    @contextlib.contextmanager
    def connection(selected):
        yield QueueRpc()

    monkeypatch.setattr(codex, "connection", connection)
    message = outgoing("literal $(message)\nsecond line")
    assert codex.Codex().send(codex_target(), message) == "queued"
    assert calls[-1] == ("thread/queue/add", {"threadId": "root-id", "clientUserMessageId": message.id,
                                            "input": [{"type": "text", "text": message.text}]})


def test_discovery_disappearance_and_reconnect_leave_no_registry_rows(store, provider, monkeypatch):
    seed = store.register(target())
    now = [100]
    monkeypatch.setattr("agent_inbox.catalog.time.monotonic", lambda: now[0])
    found = [RootInfo("first", "Root first", "active"), RootInfo("new", "Second root", "idle")]
    scans = []

    def discover(selected):
        scans.append(selected.session_id)
        return list(found)

    monkeypatch.setattr(provider, "discover", discover)
    catalog = Catalog(store)
    first = catalog.listing()["roots"]
    other_id = next(row["id"] for row in first if row["id"] != seed.id)
    assert catalog.target(other_id).session_id == "new"
    assert len(scans) == 1  # concurrent phone views reuse one short discovery cache
    assert store.targets() == [seed]
    found[0] = RootInfo("first", "Renamed native task", "idle")
    now[0] += 11
    renamed = catalog.listing()["roots"]
    assert next(row for row in renamed if row["id"] == seed.id)["label"] == "Renamed native task"
    assert store.targets() == [seed]
    found.clear()
    now[0] += 11
    assert catalog.listing()["roots"] == []
    with pytest.raises(ValueError):
        catalog.target(other_id)
    found.append(RootInfo("new", "Second root", "idle"))
    now[0] += 11
    assert catalog.listing()["roots"][0]["id"] == other_id
    assert store.targets() == [seed]


def test_catalog_scans_shared_connection_once_and_hides_unavailable_sources(store, provider, monkeypatch):
    store.register(target())
    store.register(target("second"))
    calls = []

    def discover(seed):
        calls.append(seed.id)
        raise ConnectionError("private diagnostic")

    monkeypatch.setattr(provider, "discover", discover)
    listing = Catalog(store).listing()
    assert len(calls) == 1
    assert listing == {"roots": [], "warnings": ["Fixture connection unavailable"]}


def test_steered_receipt_can_be_retried_after_session_goes_offline(store, provider, monkeypatch):
    store.register(target())
    app, data = App(store), submission()
    sent = []

    def send(selected, message):
        sent.append(message.text)
        return "steered"

    monkeypatch.setattr(provider, "send", send)
    assert app.send(data)["status"] == "steered"

    def offline(identifier):
        raise ValueError("Root offline")

    monkeypatch.setattr(app.catalog, "target", offline)
    assert app.send(data)["status"] == "steered"
    assert sent == [data["text"]]


class SteeringRpc:
    def __init__(self, pages, error=None):
        self.pages = iter(pages)
        self.error = error
        self.calls = []

    def call(self, method, params):
        self.calls.append((method, params))
        if method == "thread/read":
            return {"thread": {**codex_root(), "status": {"type": "active", "activeFlags": []}}}
        if method == "thread/turns/list":
            return {"data": next(self.pages)}
        if method == "turn/steer":
            if self.error:
                raise self.error
            return {"turnId": params["expectedTurnId"]}
        raise AssertionError("Unexpected method: " + method)


def use_rpc(monkeypatch, rpc):
    @contextlib.contextmanager
    def connection(selected):
        yield rpc

    monkeypatch.setattr(codex, "connection", connection)


def outgoing(body="Change direction", images=None):
    return Outgoing("62c72a25-46ab-48ac-8aac-250cb6e1882d", body, images or [])


def test_busy_root_steers_the_authoritative_turn_without_queueing(monkeypatch):
    rpc = SteeringRpc([[{"id": "finished", "status": "completed"},
                        {"id": "current", "status": "inProgress"}]])
    use_rpc(monkeypatch, rpc)
    assert codex.Codex().send(codex_target(), outgoing()) == "steered"
    method, params = rpc.calls[-1]
    assert method == "turn/steer"
    assert params == {"threadId": "root-id", "expectedTurnId": "current",
                      "input": [{"type": "text", "text": "Change direction"}],
                      "clientUserMessageId": outgoing().id}


def test_active_turn_metadata_is_rechecked_once_before_rejecting(monkeypatch):
    rpc = SteeringRpc([[], []])
    use_rpc(monkeypatch, rpc)
    with pytest.raises(DeliveryRejected):
        codex.Codex().send(codex_target(), outgoing())
    assert sum(method == "thread/turns/list" for method, _ in rpc.calls) == 2
    assert not any(method == "turn/steer" for method, _ in rpc.calls)


def test_active_turn_metadata_can_become_available_on_second_read(monkeypatch):
    rpc = SteeringRpc([[], [{"id": "current", "status": "inProgress"}]])
    use_rpc(monkeypatch, rpc)
    assert codex.Codex().send(codex_target(), outgoing()) == "steered"
    assert sum(method == "turn/steer" for method, _ in rpc.calls) == 1


@pytest.mark.parametrize("error", [TimeoutError(), RuntimeError("stale turn rejected")])
def test_lost_or_rejected_steer_is_never_repeated_or_queued(monkeypatch, error):
    rpc = SteeringRpc([[{"id": "current", "status": "inProgress"}]], error)
    use_rpc(monkeypatch, rpc)
    with pytest.raises(type(error)):
        codex.Codex().send(codex_target(), outgoing())
    assert sum(method == "turn/steer" for method, _ in rpc.calls) == 1


@pytest.mark.parametrize("data", [[{"id": "t", "status": "invented"}],
                                  [{"id": "a", "status": "inProgress"},
                                   {"id": "b", "status": "inProgress"}]])
def test_active_turn_decoder_rejects_unreliable_metadata(data):
    with pytest.raises(ValueError):
        codex.active_turn({"data": data})


def test_codex_discovery_excludes_workers_and_unloaded_sessions(monkeypatch):
    infos = {
        "root-id": {**codex_root(), "name": "Main task"},
        "worker": {**codex_root(), "id": "worker", "sessionId": "root-id", "parentThreadId": "root-id"},
        "closed": {**codex_root(), "id": "closed", "sessionId": "closed",
                   "status": {"type": "notLoaded"}},
        "blank": {**codex_root(), "id": "blank", "sessionId": "blank"},
    }

    class DiscoveryRpc:
        def call(self, method, params):
            if method == "thread/loaded/list":
                return {"data": list(infos)}
            if method == "thread/turns/list":
                if params["threadId"] == "blank":
                    raise codex.RpcRejected(-32600, "thread blank is not materialized yet; "
                                           "thread/turns/list is unavailable before first user message")
                return {"data": []}
            assert method == "thread/read"
            return {"thread": infos[params["threadId"]]}

    use_rpc(monkeypatch, DiscoveryRpc())
    assert codex.Codex().discover(codex_target()) == [RootInfo("root-id", "Main task", "idle")]


def test_ended_turn_rejection_is_not_dispatched_again(monkeypatch):
    rpc = SteeringRpc([[{"id": "current", "status": "inProgress"}]],
                      codex.RpcRejected(-32600, "no active turn to steer"))
    use_rpc(monkeypatch, rpc)
    with pytest.raises(DeliveryRejected):
        codex.Codex().send(codex_target(), outgoing())
    assert sum(method == "turn/steer" for method, _ in rpc.calls) == 1


@pytest.mark.parametrize("code,expected", [(-32600, codex.RpcRejected), (True, ValueError)])
def test_rpc_error_boundary_preserves_codes_without_disclosing_details(code, expected):
    class Stream:
        def send(self, value):
            pass

        def recv(self, **kwargs):
            return json.dumps({"id": 1, "error": {"code": code, "message": "private diagnostic"}})

    with pytest.raises(expected) as error:
        codex.Rpc(Stream()).call("thread/read", {"threadId": "root-id"})
    assert "private" not in str(error.value)


def history_page(items, next_cursor=None, previous="head"):
    return {"data": [{"turnId": "t", "item": item} for item in items],
            "nextCursor": next_cursor, "backwardsCursor": previous}


def test_question_reply_renders_choices_without_control_envelope_or_internal_ids():
    body = "<send_user_message_question_reply>" + json.dumps([
        {"question": "Which cleanup?", "answer": "Inbox only", "questionItemId": "private-routing-reference"},
        {"question": "When?", "answer": "Now", "questionItemId": "second-reference"},
    ]) + "</send_user_message_question_reply>"
    page = codex_history.decode_page(history_page([
        {"id": "reply", "type": "userMessage", "content": [{"type": "text", "text": body}]},
    ]))
    message = page.messages[0]
    assert [(reply.question, reply.answer) for reply in message.answers] == [
        ("Which cleanup?", "Inbox only"), ("When?", "Now"),
    ]
    value = json.dumps(Snapshot("idle", True, [message]).json())
    assert "private-routing-reference" not in value
    assert "send_user_message_question_reply" not in value
    assert "Inbox only" in value


def test_malformed_question_reply_is_rejected_as_a_visible_notice():
    body = '<send_user_message_question_reply>{"answer":1}</send_user_message_question_reply>'
    page = codex_history.decode_page(history_page([
        {"id": "reply", "type": "userMessage", "content": [{"type": "text", "text": body}]},
    ]))
    assert "could not be displayed" in page.messages[0].text
    assert page.messages[0].answers is None


def test_forward_catchup_preserves_intermediate_progress_across_multiple_pages():
    records = [{"id": str(index), "type": "agentMessage", "phase": "commentary",
                "text": "Progress " + str(index)} for index in range(201)]

    class HistoryRpc:
        def call(self, method, params):
            assert method == "thread/items/list"
            if params["sortDirection"] == "desc":
                return history_page([records[-1]], previous="tail-200")
            if params["cursor"] == "start":
                return history_page(records[:100], "continue", "old")
            assert params["cursor"] == "continue"
            return history_page(records[100:], previous="old")

    rpc = HistoryRpc()
    first = codex_history.history(rpc, "root", since="start")
    assert first.catching_up and first.newer == "continue"
    second = codex_history.history(rpc, "root", since=first.newer)
    assert not second.catching_up and second.newer == "tail-200"
    merged = first.messages + second.messages
    assert [m.text for m in merged] == ["Progress " + str(index) for index in range(201)]
    assert all(m.phase == "commentary" for m in merged)


def test_catchup_revisits_current_message_without_exposing_reasoning():
    class HistoryRpc:
        def call(self, method, params):
            return history_page([{"id": "same", "type": "agentMessage", "text": "Updated response"}],
                                previous="same-anchor")

    page = codex_history.history(HistoryRpc(), "root", since="same-anchor")
    assert page.messages[0].text == "Updated response"
    assert page.newer == "same-anchor"
    assert not page.catching_up


def test_markdown_is_readable_and_does_not_execute_embedded_html():
    message = Message("m", "assistant", "**Question**\n\n- First\n- Second\n\n`command`\n\n"
                      '<script>alert(1)</script><img src=x onerror=alert(1)>\n\n'
                      "[bad](javascript:alert(1))")
    rendered = render_snapshot(Snapshot("idle", True, [message]))["messages"][0]["html"]
    assert "<strong>Question</strong>" in rendered and "<ul>" in rendered
    assert "<code>command</code>" in rendered
    assert "<script" not in rendered and "<img" not in rendered
    assert 'href="javascript:' not in rendered

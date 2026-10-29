import json

import pytest

from agent_bridge import core, root_wake, status, watch
from agent_bridge.acknowledgements import acknowledge


@pytest.fixture
def transport(monkeypatch):
    sockets, peers = [], []
    responses = {
        "initialize": {},
        "mcpServerStatus/list": {
            "data": [{"name": "codex_tui", "tools": {"send_message_to_thread": {}}}],
            "nextCursor": None,
        },
        "mcpServer/tool/call": {
            "content": [{"type": "text", "text": '{"threadId":"root-thread"}'}],
        },
    }

    class Socket:
        closed = False

        def __init__(self, *args):
            sockets.append(self)

        def settimeout(self, timeout):
            pass

        def connect(self, path):
            self.path = path

        def close(self):
            self.closed = True

    class Peer:
        closed = False

        def __init__(self, *args, **kwargs):
            self.requests = []
            peers.append(self)

        def settimeout(self, timeout):
            pass

        def send(self, payload):
            self.requests.append(json.loads(payload))

        def recv(self):
            request = self.requests[-1]
            result = responses[request["method"]]
            if isinstance(result, list):
                result = result.pop(0)
            if isinstance(result, Exception):
                raise result
            return json.dumps({"id": request["id"], "result": result})

        def close(self):
            self.closed = True

    monkeypatch.setattr(root_wake.socket, "socket", Socket)
    monkeypatch.setattr(root_wake, "create_connection", Peer)
    return sockets, peers, responses


@pytest.mark.parametrize(
    "environment",
    [
        {},
        {"CODEX_THREAD_ID": "root-thread", "CLAUDECODE": "1"},
        {"CODEX_THREAD_ID": "root-thread", core.WORKER_FLAG: "1"},
    ],
)
def test_other_harnesses_and_workers_do_not_send_native_codex_messages(monkeypatch, transport, environment):
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    assert root_wake.prepare(["owner"]) is None
    assert not transport[0] and not transport[1]


def test_codex_preflight_and_native_send_use_separate_connections(monkeypatch, tmp_path, transport):
    monkeypatch.setenv("CODEX_THREAD_ID", "root-thread")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    delivery = root_wake.prepare(["owner"])
    assert transport[1][0].closed
    assert transport[0][0].path == str(tmp_path / "app-server-control/app-server-control.sock")
    delivery.deliver(["owner"], "event")
    assert len(transport[1]) == 2 and all(peer.closed for peer in transport[1])
    sent = transport[1][1].requests[-1]
    assert sent["method"] == "mcpServer/tool/call"
    assert sent["params"]["server"] == "codex_tui"
    assert sent["params"]["tool"] == "send_message_to_thread"
    assert sent["params"]["threadId"] == sent["params"]["arguments"]["threadId"] == "root-thread"


def test_codex_preflight_follows_status_pages(monkeypatch, transport):
    monkeypatch.setenv("CODEX_THREAD_ID", "root-thread")
    transport[2]["mcpServerStatus/list"] = [
        {"data": [], "nextCursor": "next"},
        {"data": [{"name": "codex_tui", "tools": {"send_message_to_thread": {}}}], "nextCursor": None},
    ]
    root_wake.prepare(["owner"])
    requests = [request for request in transport[1][0].requests
                if request["method"] == "mcpServerStatus/list"]
    assert [request["params"]["cursor"] for request in requests] == [None, "next"]


@pytest.mark.parametrize("pages", [
    [{"data": []}],
    [{"data": [], "nextCursor": 1}],
    [{"data": [], "nextCursor": "same"}, {"data": [], "nextCursor": "same"}],
])
def test_codex_preflight_rejects_invalid_status_pagination(monkeypatch, transport, pages):
    monkeypatch.setenv("CODEX_THREAD_ID", "root-thread")
    transport[2]["mcpServerStatus/list"] = pages
    with pytest.raises(RuntimeError, match="Invalid Codex MCP server list"):
        root_wake.prepare(["owner"])


def test_continuing_native_wake_does_not_ask_codex_to_rearm(transport):
    message = root_wake.CodexRootWake("root-thread").message(["owner"], "event", scheduled=True)
    assert "remains active" in message and "do not re-arm" in message
    assert "exited" not in message


def test_missing_native_tool_fails_before_watch_consumes_events(monkeypatch, transport):
    monkeypatch.setenv("CODEX_THREAD_ID", "root-thread")
    transport[2]["mcpServerStatus/list"] = {"data": [], "nextCursor": None}
    monkeypatch.setattr(watch, "follow", lambda *args: pytest.fail("watch started without delivery"))
    with pytest.raises(RuntimeError, match="requires codex_tui"):
        watch.watch(["owner"], until_event=True)
    assert transport[0][0].closed and transport[1][0].closed


def test_oversized_scope_fails_before_watch_consumes_events(monkeypatch, transport):
    monkeypatch.setenv("CODEX_THREAD_ID", "root-thread")
    monkeypatch.setattr(watch, "follow", lambda *args: pytest.fail("oversized callback started watch"))
    with pytest.raises(RuntimeError, match="task-message limit"):
        watch.watch(["owner" * 250], until_event=True)


def test_preflight_reserves_room_for_the_longest_notification(monkeypatch, transport):
    monkeypatch.setenv("CODEX_THREAD_ID", "root-thread")
    delivery = root_wake.CodexRootWake("root-thread")
    longest = max(
        len(delivery.message([""], reason, scheduled).encode("utf-8"))
        for reason in ("event", "timeout", "error")
        for scheduled in (False, True)
    )
    scope = ["x" * (1000 - longest + 1)]
    with pytest.raises(RuntimeError, match="task-message limit"):
        root_wake.prepare(scope)


@pytest.mark.parametrize("completed", [True, False])
def test_watch_automatically_delivers_exit_to_codex_root(monkeypatch, tmp_path, transport, completed):
    monkeypatch.setenv("CODEX_THREAD_ID", "root-thread")
    monkeypatch.setattr(watch, "JOBS", tmp_path)

    def finish(*args):
        wake = args[-2]
        wake.reason = "event" if completed else "timeout"
        if completed:
            wake.native_event_owners.add("owner")
        return completed

    monkeypatch.setattr(watch, "follow", finish)
    assert watch.watch(["owner"], until_event=True) is completed
    prompt = transport[1][1].requests[-1]["params"]["arguments"]["prompt"]
    assert ("timed out" in prompt) is not completed


@pytest.mark.parametrize(
    "result",
    [
        {"isError": True, "content": []},
        {},
        {"content": "invalid"},
        {"isError": 0, "content": []},
        {"content": []},
    ],
)
def test_rejected_native_send_is_visible_and_never_uses_another_delivery(transport, result):
    delivery = root_wake.CodexRootWake("root-thread")
    transport[2]["mcpServer/tool/call"] = result
    with pytest.raises(RuntimeError, match="not accepted"):
        delivery.deliver(["owner"], "event")
    assert len(transport[1]) == 2 and all(peer.closed for peer in transport[1])


@pytest.mark.parametrize("receipt", ["not-json", '{"threadId":"another-thread"}', "[]"])
def test_native_reply_must_confirm_the_current_thread(transport, receipt):
    delivery = root_wake.CodexRootWake("root-thread")
    transport[2]["mcpServer/tool/call"] = {"content": [{"type": "text", "text": receipt}]}
    with pytest.raises(RuntimeError, match="receipt|different thread"):
        delivery.deliver(["owner"], "event")


def test_watch_failure_notifies_root_and_preserves_the_error(monkeypatch, tmp_path, transport):
    monkeypatch.setenv("CODEX_THREAD_ID", "root-thread")
    monkeypatch.setattr(watch, "JOBS", tmp_path)

    def fail(*args):
        raise RuntimeError("observer failed")

    monkeypatch.setattr(watch, "follow", fail)
    with pytest.raises(RuntimeError, match="observer failed"):
        watch.watch(["owner"], until_event=True)
    prompt = transport[1][1].requests[-1]["params"]["arguments"]["prompt"]
    assert "failed" in prompt


def test_empty_owner_does_not_notify_root(monkeypatch, tmp_path, transport):
    monkeypatch.setenv("CODEX_THREAD_ID", "root-thread")
    monkeypatch.setattr(watch, "JOBS", tmp_path)
    monkeypatch.setattr(watch, "follow", lambda *args: True)
    assert watch.watch(["owner"], until_event=True) is True
    assert len(transport[1]) == 1


def test_failed_native_send_keeps_group_notice_pending_for_another_watch(monkeypatch, tmp_path, transport):
    monkeypatch.setenv("CODEX_THREAD_ID", "root-thread")
    monkeypatch.setattr(watch, "JOBS", tmp_path)
    monkeypatch.setattr(core, "JOBS", tmp_path)
    job = tmp_path / "owner/job"
    job.mkdir(parents=True)
    core.save(job / "state.json", {"backend": "codex"})
    core.log(job, "turn_completed")
    transport[2]["mcpServer/tool/call"] = {"isError": True, "content": []}
    with pytest.raises(RuntimeError, match="not accepted"):
        watch.watch(["owner"], until_event=True)
    pending = status.Collector(tmp_path).collect(include_quotas=False)
    assert pending.wake_events[0].kind == "completion_batch"
    assert not pending.group_events[0].seen
    transport[2]["mcpServer/tool/call"] = {
        "content": [{"type": "text", "text": '{"threadId":"root-thread"}'}],
    }
    monkeypatch.setattr(watch.time, "sleep", lambda _: acknowledge(job))
    assert watch.watch(["owner"], until_event=True) is True
    assert not status.Collector(tmp_path).collect(include_quotas=False).wake_events


def test_native_failure_does_not_replace_observer_failure(monkeypatch, tmp_path, transport):
    monkeypatch.setenv("CODEX_THREAD_ID", "root-thread")
    monkeypatch.setattr(watch, "JOBS", tmp_path)
    transport[2]["mcpServer/tool/call"] = {"isError": True, "content": []}

    def fail(*args):
        raise RuntimeError("observer failed")

    monkeypatch.setattr(watch, "follow", fail)
    with pytest.raises(RuntimeError, match="observer failed") as error:
        watch.watch(["owner"], until_event=True)
    assert "Native root delivery also failed" in error.value.__notes__[0]

import json
from pathlib import Path

import pytest

from codex_wake import client


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
            "content": [{"type": "text", "text": '{"threadId":"target-thread"}'}],
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

    monkeypatch.setattr(client.socket, "socket", Socket)
    monkeypatch.setattr(client, "create_connection", Peer)
    return sockets, peers, responses


def test_target_is_frozen_and_every_call_closes_connection(transport, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", "/target-home")
    wake = client.Wake("target-thread")
    monkeypatch.setenv("CODEX_HOME", "/another-home")
    wake.check()
    wake.send("first event")
    wake.send("second event")
    sockets, peers, _ = transport
    assert len(peers) == 3
    assert all(socket.closed and socket.path.startswith("/target-home/") for socket in sockets)
    assert all(peer.closed for peer in peers)
    for peer in peers[1:]:
        args = peer.requests[-1]["params"]
        assert args["threadId"] == args["arguments"]["threadId"] == "target-thread"


def test_preflight_uses_read_only_status_api_and_all_pages(transport):
    transport[2]["mcpServerStatus/list"] = [
        {"data": [], "nextCursor": "page2"},
        {"data": [{"name": "codex_tui", "tools": {"send_message_to_thread": {}}}], "nextCursor": None},
    ]
    client.Wake("target-thread").check()
    requests = transport[1][0].requests
    assert [
        request["params"]["cursor"] for request in requests if request["method"] == "mcpServerStatus/list"
    ] == [None, "page2"]
    assert all(request["method"] != "mcpServer/tool/call" for request in requests)


@pytest.mark.parametrize(
    "pages",
    [
        [{"data": []}],
        [{"data": [], "nextCursor": False}],
        [{"data": [], "nextCursor": "x"}, {"data": [], "nextCursor": "x"}],
    ],
)
def test_invalid_pagination_fails_and_closes(transport, pages):
    transport[2]["mcpServerStatus/list"] = pages
    with pytest.raises(RuntimeError, match="Invalid Codex MCP server list"):
        client.Wake("target-thread").check()
    assert transport[0][0].closed and transport[1][0].closed


@pytest.mark.parametrize(
    "result",
    [
        {"isError": True, "content": []},
        {"isError": 0, "content": []},
        {},
        {"content": [{"type": "text", "text": "not-json"}]},
        {"content": [{"type": "text", "text": '{"threadId":"wrong-thread"}'}]},
    ],
)
def test_rejected_or_misdirected_send_never_retries(transport, result):
    transport[2]["mcpServer/tool/call"] = result
    with pytest.raises(RuntimeError):
        client.Wake("target-thread").send("event")
    assert len(transport[1]) == 1
    assert transport[0][0].closed and transport[1][0].closed


def test_unavailable_capability_does_not_send(transport):
    transport[2]["mcpServerStatus/list"] = {"data": [], "nextCursor": None}
    with pytest.raises(RuntimeError, match="requires codex_tui"):
        client.Wake("target-thread").check()


def test_transport_failure_is_bounded_and_does_not_echo_server_data(transport):
    transport[2]["mcpServer/tool/call"] = OSError("private response")
    with pytest.raises(RuntimeError, match="failed \\(OSError\\)") as error:
        client.Wake("target-thread").send("event")
    assert "private response" not in str(error.value)
    assert transport[0][0].closed and transport[1][0].closed


@pytest.mark.parametrize("thread", [None, "", "a\nb", "x" * 201, 1])
def test_invalid_target_never_opens_connection(transport, thread):
    with pytest.raises(RuntimeError, match="target thread"):
        client.Wake(thread)
    assert not transport[0]


def test_message_limit_is_utf8_bytes_and_checked_before_connecting(transport):
    client.validate_message("é" * 500)
    with pytest.raises(RuntimeError, match="task-message limit"):
        client.Wake("target-thread").send("é" * 501)
    assert not transport[0]


def test_explicit_home_wins_over_environment(monkeypatch):
    monkeypatch.setenv("CODEX_HOME", "/another-home")
    assert client.Wake("target-thread", "/explicit-home").home == Path("/explicit-home")

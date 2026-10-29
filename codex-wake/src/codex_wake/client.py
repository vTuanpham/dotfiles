"""Deliver through the current Codex app server's native task-message tool."""

import json
import os
import socket
import time
from contextlib import contextmanager
from pathlib import Path

from websocket import WebSocketException, create_connection

TIMEOUT = 15
MAX_RESPONSE = 8 * 1024 * 1024
MAX_MESSAGE = 1000


def validate_message(prompt):
    if not isinstance(prompt, str) or not prompt.strip():
        raise RuntimeError("Codex task notification must be nonempty text")
    if len(prompt.encode("utf-8")) > MAX_MESSAGE:
        raise RuntimeError("Notification exceeds Codex native task-message limit (1000 UTF-8 bytes)")


@contextmanager
def connection(home):
    transport = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    transport.settimeout(TIMEOUT)
    websocket = None
    sequence = 0

    def call(method, params):
        nonlocal sequence
        sequence += 1
        websocket.send(json.dumps({"id": sequence, "method": method, "params": params}))
        deadline = time.monotonic() + TIMEOUT
        while time.monotonic() < deadline:
            websocket.settimeout(max(0.1, deadline - time.monotonic()))
            payload = websocket.recv()
            if not isinstance(payload, str) or len(payload.encode("utf-8")) > MAX_RESPONSE:
                raise RuntimeError("Invalid Codex wake delivery response")
            response = json.loads(payload)
            if not isinstance(response, dict):
                raise RuntimeError("Invalid Codex wake delivery response")
            if response.get("id") != sequence or "method" in response:
                continue
            if "error" in response:
                raise RuntimeError(f"Codex wake delivery rejected {method}")
            result = response.get("result")
            if not isinstance(result, dict):
                raise RuntimeError("Invalid Codex wake delivery result")
            return result
        raise RuntimeError(f"Codex wake delivery timed out: {method}")

    try:
        transport.connect(str(home / "app-server-control/app-server-control.sock"))
        websocket = create_connection(
            "ws://localhost/",
            socket=transport,
            timeout=TIMEOUT,
            suppress_origin=True,
        )
        call(
            "initialize",
            {
                "clientInfo": {"name": "codex_wake", "version": "0.1.0"},
                "capabilities": {"experimentalApi": True},
            },
        )
        websocket.send(json.dumps({"method": "initialized"}))
        yield call
    except (OSError, WebSocketException, ValueError) as exc:
        raise RuntimeError(f"Codex native wake delivery failed ({type(exc).__name__})") from None
    finally:
        if websocket is not None:
            websocket.close()
        transport.close()


class Wake:
    def __init__(self, thread, home=None):
        if (
            not isinstance(thread, str)
            or not thread
            or len(thread) > 200
            or any(ord(char) < 32 for char in thread)
        ):
            raise RuntimeError("Invalid Codex target thread for wake delivery")
        self.thread = thread
        self.home = Path(home or os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser()

    def check(self):
        """Preflight the target's capability without sending a notification."""
        cursor = None
        seen_cursors = set()
        with connection(self.home) as call:
            while True:
                result = call(
                    "mcpServerStatus/list",
                    {
                        "threadId": self.thread,
                        "serverName": "codex_tui",
                        "detail": "toolsAndAuthOnly",
                        "cursor": cursor,
                        "limit": 10,
                    },
                )
                servers, next_cursor = result.get("data"), result.get("nextCursor")
                if (
                    not isinstance(servers, list)
                    or "nextCursor" not in result
                    or next_cursor is not None
                    and type(next_cursor) is not str
                ):
                    raise RuntimeError("Invalid Codex MCP server list response")
                if any(
                    isinstance(server, dict)
                    and server.get("name") == "codex_tui"
                    and isinstance(server.get("tools"), dict)
                    and "send_message_to_thread" in server["tools"]
                    for server in servers
                ):
                    return
                if next_cursor is None:
                    break
                if next_cursor in seen_cursors:
                    raise RuntimeError("Invalid Codex MCP server list cursor")
                seen_cursors.add(next_cursor)
                cursor = next_cursor
        raise RuntimeError("Codex native wake delivery requires codex_tui.send_message_to_thread")

    def send(self, prompt):
        """Send once; an uncertain response must not cause an automatic duplicate."""
        validate_message(prompt)
        with connection(self.home) as call:
            result = call(
                "mcpServer/tool/call",
                {
                    "threadId": self.thread,
                    "server": "codex_tui",
                    "tool": "send_message_to_thread",
                    "arguments": {"threadId": self.thread, "prompt": prompt},
                },
            )
        error, content = result.get("isError"), result.get("content")
        if (
            error is not None
            and type(error) is not bool
            or error is True
            or not isinstance(content, list)
            or len(content) != 1
            or not isinstance(content[0], dict)
            or content[0].get("type") != "text"
            or not isinstance(content[0].get("text"), str)
        ):
            raise RuntimeError("Codex native task notification was not accepted")
        try:
            receipt = json.loads(content[0]["text"])
        except ValueError:
            raise RuntimeError("Invalid Codex native task notification receipt") from None
        if not isinstance(receipt, dict) or receipt.get("threadId") != self.thread:
            raise RuntimeError("Codex native task notification targeted a different thread")

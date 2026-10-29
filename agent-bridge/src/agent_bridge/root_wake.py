"""Native completion delivery for roots whose background terminals do not resume turns."""

import json
import os
import socket
import time
from contextlib import contextmanager

from websocket import WebSocketException, create_connection

from .codex import real_home
from .core import WORKER_FLAG

TIMEOUT = 15
MAX_RESPONSE = 8 * 1024 * 1024


@contextmanager
def connection():
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
            if not isinstance(payload, str) or len(payload) > MAX_RESPONSE:
                raise RuntimeError("Invalid Codex watch delivery response")
            response = json.loads(payload)
            if not isinstance(response, dict):
                raise RuntimeError("Invalid Codex watch delivery response")
            if response.get("id") != sequence or "method" in response:
                continue
            if "error" in response:
                raise RuntimeError(f"Codex watch delivery rejected {method}")
            result = response.get("result")
            if not isinstance(result, dict):
                raise RuntimeError("Invalid Codex watch delivery result")
            return result
        raise RuntimeError(f"Codex watch delivery timed out: {method}")

    try:
        transport.connect(str(real_home() / "app-server-control/app-server-control.sock"))
        websocket = create_connection(
            "ws://localhost/",
            socket=transport,
            timeout=TIMEOUT,
            suppress_origin=True,
        )
        call(
            "initialize",
            {
                "clientInfo": {"name": "agent_bridge_watch", "version": "1"},
                "capabilities": {"experimentalApi": True},
            },
        )
        websocket.send(json.dumps({"method": "initialized"}))
        yield call
    except (OSError, WebSocketException, ValueError) as exc:
        raise RuntimeError(f"Codex native watch delivery failed ({type(exc).__name__})") from None
    finally:
        if websocket is not None:
            websocket.close()
        transport.close()


class CodexRootWake:
    def __init__(self, thread):
        if (
            not isinstance(thread, str)
            or not thread
            or len(thread) > 200
            or any(ord(char) < 32 for char in thread)
        ):
            raise RuntimeError("Invalid Codex root thread for watch delivery")
        self.thread = thread
        cursor = None
        seen_cursors = set()
        found = False
        with connection() as call:
            while True:
                result = call(
                    "mcpServerStatus/list",
                    {
                        "threadId": thread,
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
                    or next_cursor is not None and type(next_cursor) is not str
                ):
                    raise RuntimeError("Invalid Codex MCP server list response")
                if any(
                    isinstance(server, dict)
                    and server.get("name") == "codex_tui"
                    and isinstance(server.get("tools"), dict)
                    and "send_message_to_thread" in server["tools"]
                    for server in servers
                ):
                    found = True
                    break
                if next_cursor is None:
                    break
                if next_cursor in seen_cursors:
                    raise RuntimeError("Invalid Codex MCP server list cursor")
                seen_cursors.add(next_cursor)
                cursor = next_cursor
        if not found:
            raise RuntimeError("Codex native watch delivery requires codex_tui.send_message_to_thread")

    def message(self, owners, reason, scheduled=False):
        outcome = {"event": "found a wake event", "timeout": "timed out", "error": "failed"}[reason]
        next_step = "This watch remains active for scheduled wakes; do not re-arm it." if scheduled else (
            "This watch exited; re-arm only if jobs are still running or status shows a new schedule."
        )
        prompt = (
            f"Bridge watch for {', '.join(owners)} {outcome}. Handle pending group, critical or "
            f"overdue-reminder events and results. {next_step} Continue authorized work. "
            "This is an automatic task notification, not user approval."
        )
        if len(prompt.encode("utf-8")) > 1000:
            raise RuntimeError("Watch owner scope exceeds Codex native task-message limit")
        return prompt

    def deliver(self, owners, reason, scheduled=False):
        prompt = self.message(owners, reason, scheduled)
        with connection() as call:
            result = call(
                "mcpServer/tool/call",
                {
                    "threadId": self.thread,
                    "server": "codex_tui",
                    "tool": "send_message_to_thread",
                    "arguments": {"threadId": self.thread, "prompt": prompt},
                },
            )
        error = result.get("isError")
        content = result.get("content")
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
            raise RuntimeError("Codex native watch notification was not accepted")
        try:
            receipt = json.loads(content[0]["text"])
        except ValueError:
            raise RuntimeError("Invalid Codex native watch notification receipt") from None
        if not isinstance(receipt, dict) or receipt.get("threadId") != self.thread:
            raise RuntimeError("Codex native watch notification targeted a different thread")


def prepare(owners):
    if (
        os.environ.get(WORKER_FLAG)
        or os.environ.get("CLAUDECODE") == "1"
        or not os.environ.get("CODEX_THREAD_ID")
    ):
        return None
    delivery = CodexRootWake(os.environ["CODEX_THREAD_ID"])
    for reason in ("event", "timeout", "error"):
        delivery.message(owners, reason, True)
        delivery.message(owners, reason, False)
    return delivery

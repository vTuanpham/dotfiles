"""Native live-session listing plus the official read-only history SDK."""

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

from . import claude_history
from .capabilities import AdapterCapabilities
from .claude_channel import channel_call
from .context import SessionContext, Worker
from .models import DeliveryRejected, RootInfo, Snapshot, decode_json, fields, text


def settings(target):
    fields(target.settings, ("command", "config_dir", "channels"))
    for key in ("command", "config_dir", "channels"):
        value = text(target.settings[key], "native " + key, 4096)
        if not Path(value).is_absolute():
            raise ValueError("Native paths must be absolute")
    return target.settings


def sessions(target):
    config = settings(target)
    result = subprocess.run([config["command"], "agents", "--json"], capture_output=True,
                            env={**os.environ, "CLAUDE_CONFIG_DIR": config["config_dir"]}, timeout=8)
    if result.returncode or len(result.stdout) > 1024 * 1024:
        raise RuntimeError("Native Claude session listing unavailable")
    value = decode_json(result.stdout)
    if type(value) is not list:
        raise ValueError("Invalid native session list")
    live, seen = [], set()
    for row in value:
        if type(row) is not dict or row.get("kind") not in ("interactive", "background"):
            raise ValueError("Invalid native session record")
        identifier = row.get("sessionId")
        if identifier is None:
            continue
        if row["kind"] == "background" and "pid" not in row and "status" not in row:
            continue  # Native listing also includes exited jobs; this adapter never restarts them.
        if (type(identifier) is not str or str(uuid.UUID(identifier)) != identifier
                or identifier in seen or type(row.get("pid")) is not int or row["pid"] <= 0):
            raise ValueError("Ambiguous native session identity")
        seen.add(identifier)
        if row.get("status") not in ("busy", "waiting", "idle"):
            raise ValueError("Unsupported native session status")
        directory = text(row["cwd"], "native project", 4096)
        if not Path(directory).is_absolute():
            raise ValueError("Native project must be absolute")
        live.append(row)
    return live


def read(target, live, operation):
    config = settings(target)
    request = {"session": live["sessionId"], "directory": live["cwd"], "operation": operation}
    result = subprocess.run([sys.executable, "-m", "agent_inbox.claude_reader"],
                            input=json.dumps(request).encode(), capture_output=True, timeout=10,
                            env={**os.environ, "CLAUDE_CONFIG_DIR": config["config_dir"]})
    if result.returncode or len(result.stdout) > 24 * 1024 * 1024:
        raise RuntimeError("Native SDK read unavailable")
    value = decode_json(result.stdout)
    if value["info"]["session_id"] != live["sessionId"]:
        raise ValueError("SDK returned a different native session")
    return value


def root(target):
    found = [row for row in sessions(target) if row["sessionId"] == target.session_id]
    if len(found) != 1:
        raise DeliveryRejected("This native session is offline")
    return found[0]


def activity(info):
    return {"busy": "active", "waiting": "input-needed", "idle": "idle"}[info["status"]]


class Claude:
    capabilities = AdapterCapabilities(
        queued_messages=False, mid_turn_steering=False, approvals_survive_restart=False,
        history_while_unloaded=False, images=True, interrupt=False, commands=False, questions=False,
        reply_mode="opt_in_next_turn",
    )

    def discover(self, seed):
        result = []
        for row in sessions(seed):
            try:
                info = read(seed, row, "info")["info"]
            except RuntimeError:
                continue  # Unmaterialized or sidechain transcripts are not root conversations.
            label = row.get("name") or info.get("custom_title") or info["summary"] or row["sessionId"][-8:]
            result.append(RootInfo(row["sessionId"], text(label, "session title", 200), activity(row)))
        return result

    def snapshot(self, target, cursor=None, since=None):
        live = root(target)
        value = read(target, live, "history")
        rows = value["messages"]
        if type(rows) is not list:
            raise ValueError("Invalid SDK history")
        if cursor and since:
            raise ValueError("Choose earlier history or catch-up")
        start, end = max(0, len(rows) - 100), len(rows)
        if since:
            offset, anchor = claude_history.cursor(since)
            if offset > len(rows) or not offset or rows[offset - 1]["uuid"] != anchor:
                raise ValueError("Native history changed; reload")
            start, end = offset - 1, min(len(rows), offset - 1 + 100)
        elif cursor:
            offset, anchor = claude_history.cursor(cursor)
            if offset > len(rows) or offset and rows[offset - 1]["uuid"] != anchor:
                raise ValueError("Native history changed; reload")
            start, end = max(0, offset - 100), offset
        connected, outgoing = False, []
        try:
            relay = channel_call(target, "history")
            connected, outgoing = relay["ready"] is True, relay["messages"]
        except (OSError, ValueError, RuntimeError):
            pass
        messages, tools, timeline = claude_history.decode(
            rows[start:end], target.session_id, outgoing, append_outgoing=not cursor)
        older = claude_history.encode_cursor(start, rows[start - 1]["uuid"]) if start else None
        newer = claude_history.encode_cursor(end, rows[end - 1]["uuid"]) if end else None
        return Snapshot(activity(live), connected, messages, older,
                        newer_cursor=newer, catching_up=bool(since and end < len(rows)),
                        activity=tools, timeline=timeline)

    def send(self, target, message):
        root(target)
        result = channel_call(target, "send", {"id": message.id, "text": message.text,
                                                "images": message.images})
        if result.get("id") != message.id or result.get("status") != "forwarded":
            raise RuntimeError("Channel did not confirm its transport write")
        return "forwarded"

    def context(self, target):
        live = root(target)
        value = read(target, live, "history")
        children = value["children"]
        if type(children) is not list:
            raise ValueError("Invalid native subagent list")
        workers = [Worker(text(identifier, "native subagent", 200), "Subagent " + identifier, "unknown")
                   for identifier in children]
        return SessionContext(workers=workers, notices=[
            "Native subagent liveness and account quota are not exposed by this connection."])

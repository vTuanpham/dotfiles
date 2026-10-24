"""Translate native model/effort selectors and session actions into inbox controls."""

import time

from .commands import Choice, Command, Commands
from .models import text


def commands(rpc, info):
    models, cursor, seen = [], None, set()
    deadline = time.monotonic() + 8
    while True:
        page = rpc.call("model/list", {"limit": 100, "includeHidden": False, "cursor": cursor})
        if type(page["data"]) is not list:
            raise ValueError("Invalid native model list")
        models.extend(page["data"])
        cursor = page["nextCursor"]
        if cursor is None:
            break
        text(cursor, "model cursor", 4096)
        if cursor in seen or time.monotonic() > deadline:
            raise ValueError("Model discovery did not complete")
        seen.add(cursor)
    choices, efforts = [], []
    for model in models:
        identifier = text(model["model"], "native model", 200)
        choices.append(Choice(identifier, text(model["displayName"], "model label", 200)))
        if identifier == info.get("model"):
            if type(model["supportedReasoningEfforts"]) is not list:
                raise ValueError("Invalid native effort options")
            efforts = [Choice(text(option["reasoningEffort"], "effort", 100),
                              text(option["reasoningEffort"], "effort", 100))
                       for option in model["supportedReasoningEfforts"]]
    controls = [Command("model", "Model", "select", choices, info.get("model"), "Next turns"),
                Command("rename", "Rename", "text", description="Session title"),
                Command("compact", "Compact", "action")]
    if efforts:
        controls.insert(1, Command("effort", "Reasoning", "select", efforts,
                                   info.get("reasoningEffort"), "Next turns"))
    if info["status"]["type"] == "active":
        controls.append(Command("interrupt", "Stop turn", "action"))
    return Commands(controls, "Terminal-only pickers and sign-in remain in Codex.")


def execute(rpc, target, command, value, turn_id=None):
    if command in ("model", "effort"):
        rpc.call("thread/settings/update", {"threadId": target.session_id, command: value})
    elif command == "rename":
        rpc.call("thread/name/set", {"threadId": target.session_id,
                                    "name": text(value, "session title", 200)})
    elif command == "compact":
        rpc.call("thread/compact/start", {"threadId": target.session_id})
    elif command == "interrupt" and turn_id:
        rpc.call("turn/interrupt", {"threadId": target.session_id, "turnId": turn_id})
    else:
        raise ValueError("Unsupported native action")

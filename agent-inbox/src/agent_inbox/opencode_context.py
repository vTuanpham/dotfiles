"""Session-local usage and descendants; provider account allowance is not inferred."""

import math
import time
from urllib.parse import urlencode

from .context import Metric, SessionContext, Tool, Worker
from .models import text
from .opencode_history import page
from .opencode_http import location_query


def workers(api, identifier, running):
    result, seen, frontier = [], {identifier}, [identifier]
    deadline = time.monotonic() + 8
    while frontier:
        parent, cursor, cursors = frontier.pop(), None, set()
        while True:
            if time.monotonic() > deadline:
                raise TimeoutError("Native worker discovery timed out")
            query = {"parentID": parent, "limit": "100"}
            if cursor is not None:
                query["cursor"] = cursor
            rows, _, cursor = page(api.call("GET", "/api/session?" + urlencode(query)))
            for row in rows:
                child = text(row["id"], "worker id", 200)
                if child in seen or row.get("parentID") != parent:
                    raise ValueError("Ambiguous native ancestry")
                seen.add(child)
                frontier.append(child)
                model = row.get("model")
                if model is not None:
                    model = text(model["id"], "worker model", 200)
                result.append(Worker(child, text(row.get("title", child), "worker title", 200),
                                     "active" if child in running else "idle", model))
            if cursor is None:
                break
            if cursor in cursors:
                raise ValueError("Native worker cursor did not advance")
            cursors.add(cursor)
    return result


def usage(info):
    tokens = info["tokens"]
    if type(tokens) is not dict or type(tokens["cache"]) is not dict:
        raise ValueError("Invalid native token usage")
    values = [("Input", tokens["input"], "tokens"), ("Output", tokens["output"], "tokens"),
              ("Reasoning", tokens["reasoning"], "tokens"),
              ("Cache read", tokens["cache"]["read"], "tokens"),
              ("Cache write", tokens["cache"]["write"], "tokens"),
              ("Cost", info["cost"], "USD")]
    if any(type(value) not in (int, float) or not math.isfinite(value) or value < 0
           for _, value, _ in values):
        raise ValueError("Invalid native usage measurement")
    return [Metric(*value) for value in values]


def context(api, info, running):
    result = SessionContext(notices=["This provider does not expose account identity or allowance here."])
    try:
        result.metrics = usage(info)
    except (KeyError, TypeError, ValueError):
        result.notices.append("Session usage unavailable.")
    try:
        result.workers = workers(api, info["id"], running)
    except (KeyError, TypeError, ValueError, RuntimeError, OSError, TimeoutError):
        result.notices.append("Subagents unavailable.")
    try:
        rows = api.call("GET", "/api/mcp?" + location_query(info))["data"]
        if type(rows) is not list:
            raise ValueError("Invalid native tool inventory")
        tools = []
        for row in rows:
            status = row["status"]["status"]
            if status not in ("connected", "pending", "disabled", "failed", "needs_auth"):
                raise ValueError("Unknown native tool state")
            tools.append(Tool(text(row["name"], "tool server", 200), status))
        result.tools = tools
    except (KeyError, TypeError, ValueError, RuntimeError, OSError):
        result.notices.append("Tool inventory unavailable for this session's project.")
    return result

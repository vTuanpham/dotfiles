"""Account reads use the selected root's daemon, never a global account cache."""

import time

from .context import Account, Quota, SessionContext, Tool, Worker
from .models import text


def account(rpc, info, result):
    if info["modelProvider"] != "openai":
        result.notices.append("The selected provider does not expose account quota here.")
        return
    before = rpc.call("account/read", {"refreshToken": False})["account"]
    if before is None or before.get("type") != "chatgpt":
        result.notices.append("No ChatGPT account allowance is exposed by this connection.")
        return
    limits = rpc.call("account/rateLimits/read", {"excludeResetCreditDetails": True})
    after = rpc.call("account/read", {"refreshToken": False})["account"]
    if before != after:
        raise ValueError("Account changed during quota read")
    email = before["email"]
    if email is not None:
        text(email, "account email", 320)
    identity = limits.get("accountId")
    if identity is not None:
        text(identity, "account identity", 400)
    selected_account = Account(identity, email, text(before["planType"], "account plan", 100), "connection")
    quotas = []
    buckets = limits.get("rateLimitsByLimitId")
    if buckets is None:
        buckets = {"codex": limits["rateLimits"]}
    if type(buckets) is not dict:
        raise ValueError("Invalid native quota buckets")
    for identifier, bucket in buckets.items():
        text(identifier, "quota bucket", 200)
        if type(bucket) is not dict:
            raise ValueError("Invalid native quota bucket")
        label = bucket.get("limitName") or identifier
        text(label, "quota label", 200)
        for name in ("primary", "secondary"):
            window = bucket.get(name)
            if window is None:
                continue
            used = window["usedPercent"]
            minutes, resets = window.get("windowDurationMins"), window.get("resetsAt")
            if (type(used) is not int or used < 0
                    or minutes is not None and (type(minutes) is not int or minutes <= 0)
                    or resets is not None and (type(resets) is not int or resets < 0)):
                raise ValueError("Invalid native quota window")
            quotas.append(Quota(label + " · " + name, used, minutes, resets))
    result.account, result.quotas = selected_account, quotas


def workers(rpc, root_id):
    identifiers = rpc.call("thread/loaded/list", {})["data"]
    if type(identifiers) is not list:
        raise ValueError("Invalid native thread list")
    records, deadline = {}, time.monotonic() + 8
    for identifier in identifiers:
        text(identifier, "thread id", 200)
        if identifier in records:
            raise ValueError("Duplicate native thread identity")
        if time.monotonic() > deadline:
            raise TimeoutError("Native worker discovery timed out")
        info = rpc.call("thread/read", {"threadId": identifier})["thread"]
        if type(info) is not dict or info["id"] != identifier or "parentThreadId" not in info:
            raise ValueError("Invalid native worker metadata")
        records[identifier] = info
    descendants, frontier = [], [root_id]
    seen = {root_id}
    while frontier:
        parent = frontier.pop()
        for identifier, info in records.items():
            if info["parentThreadId"] != parent:
                continue
            if identifier in seen:
                raise ValueError("Ambiguous native ancestry")
            seen.add(identifier)
            frontier.append(identifier)
            label = info.get("agentNickname") or info.get("name") or identifier[-8:]
            status = info["status"]["type"]
            if status not in ("active", "idle", "notLoaded", "systemError"):
                raise ValueError("Unknown worker status")
            model = info.get("model")
            if model is not None:
                text(model, "worker model", 200)
            descendants.append(Worker(identifier, text(label, "worker label", 200), status, model))
    return descendants


def tools(rpc, root_id):
    result, cursor, seen = [], None, set()
    deadline = time.monotonic() + 8
    while True:
        if time.monotonic() > deadline:
            raise TimeoutError("Native tool discovery timed out")
        page = rpc.call("mcpServerStatus/list", {"threadId": root_id, "limit": 100,
                                                "cursor": cursor, "detail": "toolsAndAuthOnly"})
        if type(page["data"]) is not list:
            raise ValueError("Invalid native tool inventory")
        for server in page["data"]:
            status = server.get("runtimeStatus")
            if status is None:
                state = "unknown"
            elif type(status) is str:
                state = text(status, "tool status", 100)
            else:
                raise ValueError("Invalid native tool status")
            if type(server["tools"]) is not dict:
                raise ValueError("Invalid native tool inventory")
            result.append(Tool(text(server["name"], "tool server", 200), state, len(server["tools"])))
        cursor = page["nextCursor"]
        if cursor is None:
            return result
        text(cursor, "tool cursor", 4096)
        if cursor in seen:
            raise ValueError("Tool cursor did not advance")
        seen.add(cursor)


def context(rpc, info):
    result = SessionContext()
    for read, label in ((lambda: account(rpc, info, result), "Account allowance"),
                        (lambda: result.workers.extend(workers(rpc, info["id"])), "Subagents"),
                        (lambda: result.tools.extend(tools(rpc, info["id"])), "Tool inventory")):
        try:
            read()
        except (OSError, ValueError, KeyError, TypeError, RuntimeError, TimeoutError):
            result.notices.append(label + " unavailable from the native connection.")
    return result

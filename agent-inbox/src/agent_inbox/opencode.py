"""Existing OpenCode v2 sessions, using the same server as its terminal UI."""

import time
from urllib.parse import quote, urlencode

from . import opencode_commands, opencode_context, opencode_forms, opencode_history
from .models import DeliveryRejected, RootInfo, Snapshot, fields, text
from .opencode_http import ApiRejected, Connection


def session_path(identifier):
    text(identifier, "OpenCode session id", 200)
    if not identifier.startswith("ses_") or any(not (c.isalnum() or c in "_-") for c in identifier):
        raise ValueError("Invalid OpenCode session id")
    return "/api/session/" + quote(identifier, safe="")


def root(api, identifier):
    value = api.call("GET", session_path(identifier))
    fields(value, ("data",))
    info = value["data"]
    if (type(info) is not dict or info["id"] != identifier or "parentID" in info
            or type(info["time"]) is not dict or "archived" in info["time"]):
        raise ValueError("Expected an unarchived native root")
    return info


def active(api):
    value = api.call("GET", "/api/session/active")
    fields(value, ("data",))
    if type(value["data"]) is not dict:
        raise ValueError("Invalid native active sessions")
    for identifier, state in value["data"].items():
        session_path(identifier)
        fields(state, ("type",))
        if state["type"] != "running":
            raise ValueError("Unknown native session state")
    return value["data"]


class OpenCode:
    def context(self, target):
        api = Connection(target)
        return opencode_context.context(api, root(api, target.session_id), active(api))

    def forms(self, target):
        api = Connection(target)
        root(api, target.session_id)
        return opencode_forms.read(api, session_path(target.session_id), target.session_id)

    def answer(self, target, identifier, answer, cancel=False):
        api = Connection(target)
        root(api, target.session_id)
        path = session_path(target.session_id)
        question = opencode_forms.read(api, path, target.session_id).selected(identifier)
        if not cancel:
            question.validate(answer)
        operation = "/cancel" if cancel else "/reply"
        try:
            api.call("POST", path + opencode_forms.form_path(identifier) + operation,
                     None if cancel else {"answer": answer})
        except ApiRejected as error:
            if error.status in (400, 401, 404, 409):
                raise DeliveryRejected("Native question reply rejected") from error
            raise
        return "applied"

    def commands(self, target):
        api = Connection(target)
        return opencode_commands.commands(api, root(api, target.session_id))

    def execute(self, target, command, value):
        api = Connection(target)
        info = root(api, target.session_id)
        opencode_commands.commands(api, info).selected(command, value)
        try:
            opencode_commands.execute(api, session_path(target.session_id), command, value)
        except ApiRejected as error:
            if error.status in (400, 401, 404, 409):
                raise DeliveryRejected("Native command rejected") from error
            raise
        return "applied"

    def discover(self, seed):
        api = Connection(seed)
        running, result, seen = active(api), [], set()
        query, deadline = {"parentID": "null", "order": "desc", "limit": "100"}, time.monotonic() + 8
        while True:
            rows, _, cursor = opencode_history.page(api.call("GET", "/api/session?" + urlencode(query)))
            for info in rows:
                if info["id"] in seen or "parentID" in info or type(info["time"]) is not dict:
                    raise ValueError("Invalid discovered root")
                seen.add(info["id"])
                if "archived" in info["time"]:
                    continue
                label = text(info["title"], "root title", 200) if "title" in info else info["id"]
                result.append(RootInfo(info["id"], label, "active" if info["id"] in running else "idle",
                                       saved=info["id"] not in running))
            if cursor is None:
                return result
            if time.monotonic() > deadline or query.get("cursor") == cursor:
                raise ValueError("Native discovery did not complete")
            query = {"parentID": "null", "limit": "100", "cursor": cursor}

    def snapshot(self, target, cursor=None, since=None):
        api = Connection(target)
        root(api, target.session_id)
        status = "active" if target.session_id in active(api) else "idle"
        path, tail = session_path(target.session_id), []
        if since:
            native_cursor, last = opencode_history.decode_anchor(since)
            # The newest assistant record mutates while streaming; cursors alone would miss it.
            value = api.call("GET", path + "/message/" + quote(last, safe=""))
            fields(value, ("data",))
            if value["data"]["id"] != last:
                raise ValueError("Native message identity changed")
            tail.append(value["data"])
            query = {"limit": "100", "cursor": native_cursor}
        else:
            query = {"limit": "100", **({"cursor": cursor} if cursor else {"order": "desc"})}
        rows, previous, following = opencode_history.page(
            api.call("GET", path + "/message?" + urlencode(query)))
        ordered = [*tail, *reversed(rows)]
        newer = opencode_history.anchor(previous, rows[0]["id"]) if rows and previous else since
        if not rows and not since:
            newer = None
        messages, activity, timeline = opencode_history.projection(ordered)
        return Snapshot(status, True, messages,
                        older_cursor=None if since else following, newer_cursor=newer,
                        catching_up=bool(since and len(rows) == 100), activity=activity, timeline=timeline)

    def send(self, target, message):
        api = Connection(target)
        root(api, target.session_id)
        identifier = "msg_" + message.id.replace("-", "")
        payload = {"id": identifier, "text": message.text, "delivery": "steer",
                   "files": [{"uri": url} for url in message.images]}
        try:
            value = api.call("POST", session_path(target.session_id) + "/prompt", payload)
        except ApiRejected as error:
            if error.status in (400, 401, 404, 409):
                raise DeliveryRejected("Native input rejected") from error
            raise
        fields(value, ("data",))
        receipt = value["data"]
        if (receipt["id"] != identifier or receipt["sessionID"] != target.session_id
                or receipt["type"] != "user" or receipt["delivery"] != "steer"
                or receipt["payload"]["text"] != message.text):
            raise RuntimeError("Unrecognized native input receipt")
        return "queued"  # Admission is durable; consumption happens at the next safe boundary.

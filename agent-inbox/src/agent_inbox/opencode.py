"""Existing OpenCode v2 sessions, using the same server as its terminal UI."""

import time
from urllib.parse import quote, urlencode

from . import opencode_commands, opencode_context, opencode_forms, opencode_history, opencode_permissions
from .capabilities import AdapterCapabilities
from .forms import Forms
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
    capabilities = AdapterCapabilities(
        queued_messages=True, mid_turn_steering=True, approvals_survive_restart=True,
        history_while_unloaded=True, images=True, interrupt=True, commands=True, questions=True,
        reply_mode="direct",
    )

    def context(self, target):
        api = Connection(target)
        return opencode_context.context(api, root(api, target.session_id), active(api))

    def forms(self, target):
        api = Connection(target)
        root(api, target.session_id)
        path = session_path(target.session_id)
        questions = opencode_forms.read(api, path, target.session_id)
        permissions = opencode_permissions.read(api, path, target.session_id)
        return Forms(questions.forms + permissions.forms)

    def answer(self, target, identifier, answer, cancel=False):
        api = Connection(target)
        root(api, target.session_id)
        path = session_path(target.session_id)
        text(identifier, "question id", 200)
        permission = identifier.startswith("per_")
        questions = (opencode_permissions if permission else opencode_forms).read(
            api, path, target.session_id,
        )
        question = questions.selected(identifier)
        if not cancel:
            question.validate(answer)
        if permission:
            # 2.0.3 uses `reply`; newer online documentation calls this field `decision`.
            operation = path + opencode_permissions.permission_path(identifier) + "/reply"
            payload = {"reply": "reject" if cancel else answer["decision"]}
        else:
            operation = path + opencode_forms.form_path(identifier) + ("/cancel" if cancel else "/reply")
            payload = None if cancel else {"answer": answer}
        try:
            api.call("POST", operation, payload)
        except ApiRejected as error:
            if error.status in (404, 409):
                # A withdrawal can race the last read. Only the native pending list proves it gone.
                (opencode_permissions if permission else opencode_forms).read(
                    api, path, target.session_id,
                ).selected(identifier)
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
            if time.monotonic() > deadline:
                raise TimeoutError("Native discovery timed out")
            if query.get("cursor") == cursor:
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
        if message.delivery not in ("queue", "steer"):
            raise DeliveryRejected("Unsupported delivery mode")
        api = Connection(target)
        root(api, target.session_id)
        if message.delivery == "steer" and target.session_id not in active(api):
            raise DeliveryRejected("This root has no active turn to steer")
        identifier = "msg_" + message.id.replace("-", "")
        payload = {"id": identifier, "text": message.text, "delivery": message.delivery,
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
                or receipt["type"] != "user" or receipt["delivery"] != message.delivery
                or receipt["payload"]["text"] != message.text):
            raise RuntimeError("Unrecognized native input receipt")
        return "steered" if message.delivery == "steer" else "queued"

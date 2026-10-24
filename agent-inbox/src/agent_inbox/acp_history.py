"""Strict ACP v1 session, history, control, and cursor projection."""

import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .media import MAX_BYTES, ImageBudget, native_image
from .models import Activity, Message, decode_json, text
from .models import fields as model_fields

MAX_SESSIONS = 5000
MAX_UPDATES = 50000
PAGE_SIZE = 100
_COMMAND = re.compile(r"[A-Za-z0-9_-]{1,100}\Z")


def string(value, name, maximum=16384):
    if type(value) is not str or len(value) > maximum or "\0" in value:
        raise ValueError(f"Invalid {name}")
    return value


def fields(value, required, optional=()):
    model_fields(value, required, optional)
    for key in ("_meta", "annotations"):
        if key in value and value[key] is not None and type(value[key]) is not dict:
            raise ValueError(f"Invalid ACP {key}")
    return value


def _json_value(value, depth=0):
    if depth > 16:
        raise ValueError("ACP tool metadata is too deeply nested")
    if value is None or type(value) in (bool, int):
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("Non-finite ACP tool metadata")
        return
    if type(value) is str:
        string(value, "ACP tool metadata", 1000000)
        return
    if type(value) is list:
        if len(value) > 1000:
            raise ValueError("ACP tool metadata exceeds its limit")
        for item in value:
            _json_value(item, depth + 1)
        return
    if type(value) is dict:
        if len(value) > 1000:
            raise ValueError("ACP tool metadata exceeds its limit")
        for key, item in value.items():
            text(key, "ACP tool metadata key", 1000)
            _json_value(item, depth + 1)
        return
    raise ValueError("Invalid ACP tool metadata")


def absolute_path(value, name):
    result = text(value, name, 4096)
    if not Path(result).is_absolute():
        raise ValueError(f"{name} must be absolute")
    return result


@dataclass(frozen=True)
class Capabilities:
    load: bool
    list: bool
    resume: bool
    image: bool
    additional_directories: bool


@dataclass(frozen=True)
class Session:
    id: str
    cwd: str
    label: str
    additional_directories: list[str]


@dataclass(frozen=True)
class SessionPage:
    sessions: list[Session]
    next_cursor: str | None


@dataclass(frozen=True)
class ConfigOption:
    id: str
    name: str
    kind: str
    current: str | bool
    category: str | None
    choices: list[tuple[str, str]]


@dataclass(frozen=True)
class Mode:
    current: str
    choices: list[tuple[str, str]]


@dataclass(frozen=True)
class SlashCommand:
    name: str
    description: str
    hint: str


@dataclass(frozen=True)
class Usage:
    used: int
    size: int
    cost_amount: int | float | None = None
    currency: str | None = None


def _capability_object(value, name):
    if value is None:
        return False
    if type(value) is not dict:
        raise ValueError(f"Invalid ACP {name} capability")
    return True


def initialize(value):
    fields(value, ("protocolVersion", "agentCapabilities"), ("agentInfo", "authMethods", "_meta"))
    if type(value["protocolVersion"]) is not int or value["protocolVersion"] != 1:
        raise ValueError("ACP agent did not negotiate the supported protocol version")
    capabilities = fields(
        value["agentCapabilities"],
        (),
        (
            "loadSession",
            "promptCapabilities",
            "mcpCapabilities",
            "sessionCapabilities",
            "auth",
            "providers",
            "nes",
            "positionEncoding",
            "_meta",
        ),
    )
    load = capabilities.get("loadSession", False)
    if type(load) is not bool:
        raise ValueError("Invalid ACP load-session capability")
    prompt = capabilities.get("promptCapabilities", {})
    if type(prompt) is not dict:
        raise ValueError("Invalid ACP prompt capabilities")
    if prompt.keys() - {"image", "audio", "embeddedContext", "_meta"}:
        raise ValueError("Unknown ACP prompt capability")
    image = prompt.get("image", False)
    if type(image) is not bool:
        raise ValueError("Invalid ACP image capability")
    session = capabilities.get("sessionCapabilities", {})
    if type(session) is not dict:
        raise ValueError("Invalid ACP session capabilities")
    if session.keys() - {"list", "delete", "additionalDirectories", "fork", "resume", "close", "_meta"}:
        raise ValueError("Unknown ACP session capability")
    for name in ("list", "delete", "additionalDirectories", "fork", "resume", "close"):
        if name in session:
            _capability_object(session[name], name)
    info = value.get("agentInfo")
    if info is not None:
        fields(info, (), ("name", "title", "version", "_meta"))
        for key in ("name", "title", "version"):
            if key in info:
                text(info[key], "ACP agent info", 200)
    methods = value.get("authMethods", [])
    if type(methods) is not list:
        raise ValueError("Invalid ACP authentication methods")
    return Capabilities(
        load,
        _capability_object(session.get("list"), "session list"),
        _capability_object(session.get("resume"), "session resume"),
        image,
        _capability_object(session.get("additionalDirectories"), "additional directories"),
    )


def _session(value):
    fields(value, ("sessionId", "cwd"), ("title", "updatedAt", "additionalDirectories", "_meta"))
    identifier = text(value["sessionId"], "ACP session id", 200)
    cwd = absolute_path(value["cwd"], "ACP session directory")
    if "title" in value and value["title"] is not None:
        label = text(value["title"], "ACP session title", 200)
    else:
        label = "Antigravity " + identifier[-8:]
    if "updatedAt" in value and value["updatedAt"] is not None:
        timestamp = text(value["updatedAt"], "ACP session timestamp", 100)
        try:
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("Invalid ACP session timestamp") from error
        if parsed.tzinfo is None:
            raise ValueError("ACP session timestamp must include a timezone")
    directories = []
    if "additionalDirectories" in value and value["additionalDirectories"] is not None:
        directories = value["additionalDirectories"]
        if type(directories) is not list or len(directories) > 128:
            raise ValueError("Invalid ACP additional directories")
        seen = set()
        for directory in directories:
            path = absolute_path(directory, "ACP additional directory")
            if path == cwd or path in seen:
                raise ValueError("Duplicate ACP session directory")
            seen.add(path)
    return Session(identifier, cwd, label, directories)


def sessions_page(value):
    fields(value, ("sessions",), ("nextCursor", "_meta"))
    rows = value["sessions"]
    if type(rows) is not list or len(rows) > MAX_SESSIONS:
        raise ValueError("Invalid ACP session page")
    sessions = [_session(row) for row in rows]
    if len({row.id for row in sessions}) != len(sessions):
        raise ValueError("Duplicate ACP session id")
    cursor = value.get("nextCursor")
    if cursor is not None:
        text(cursor, "ACP session cursor", 4096)
    return SessionPage(sessions, cursor)


def _modes(value):
    if value is None:
        return None
    fields(value, ("currentModeId", "availableModes"), ("_meta",))
    current = text(value["currentModeId"], "ACP current mode", 200)
    rows = value["availableModes"]
    if type(rows) is not list or len(rows) > 100:
        raise ValueError("Invalid ACP modes")
    choices = []
    for row in rows:
        fields(row, ("id", "name"), ("description", "_meta"))
        identifier = text(row["id"], "ACP mode id", 200)
        name = text(row["name"], "ACP mode name", 200)
        if "description" in row and row["description"] is not None:
            text(row["description"], "ACP mode description", 1000)
        choices.append((identifier, name))
    if len({key for key, _ in choices}) != len(choices) or current not in {key for key, _ in choices}:
        raise ValueError("ACP mode selection is ambiguous")
    return Mode(current, choices)


def _config_options(value):
    if value is None:
        return []
    if type(value) is not list or len(value) > 100:
        raise ValueError("Invalid ACP configuration options")
    result = []
    for row in value:
        if type(row) is not dict:
            raise ValueError("Invalid ACP configuration option")
        kind = row.get("type")
        if type(kind) is not str:
            raise ValueError("Missing ACP configuration option type")
        if kind not in ("select", "boolean"):
            continue
        common = ("id", "name", "currentValue", "type")
        optional = ("description", "category", "_meta")
        if kind == "select":
            fields(row, (*common, "options"), optional)
            options = row["options"]
            if type(options) is not list or not 1 <= len(options) <= 200:
                raise ValueError("Invalid ACP configuration choices")
            grouped = "group" in options[0]
            choice_rows = []
            if grouped:
                group_ids = set()
                for group in options:
                    fields(group, ("group", "name", "options"), ("_meta",))
                    group_id = text(group["group"], "ACP configuration group id", 200)
                    if group_id in group_ids:
                        raise ValueError("Duplicate ACP configuration group")
                    group_ids.add(group_id)
                    group_name = text(group["name"], "ACP configuration group", 200)
                    if type(group["options"]) is not list or not group["options"]:
                        raise ValueError("Invalid ACP grouped choices")
                    for option in group["options"]:
                        fields(option, ("value", "name"), ("description", "_meta"))
                        choice_rows.append((option, group_name))
            else:
                for option in options:
                    fields(option, ("value", "name"), ("description", "_meta"))
                    choice_rows.append((option, None))
            choices = []
            for option, group_name in choice_rows:
                label = text(option["name"], "ACP option name", 200)
                if group_name is not None:
                    label = group_name + " · " + label
                choices.append((text(option["value"], "ACP option value", 200), label))
            if len({key for key, _ in choices}) != len(choices):
                raise ValueError("Duplicate ACP configuration choice")
            current = text(row["currentValue"], "ACP current option", 200)
            if current not in {key for key, _ in choices}:
                raise ValueError("ACP current option is not advertised")
        elif kind == "boolean":
            fields(row, common, optional)
            if type(row["currentValue"]) is not bool:
                raise ValueError("Invalid ACP boolean configuration")
            current = row["currentValue"]
            choices = [("true", "On"), ("false", "Off")]
        identifier = text(row["id"], "ACP configuration id", 200)
        name = text(row["name"], "ACP configuration name", 200)
        category = row.get("category")
        if category is not None:
            text(category, "ACP configuration category", 100)
        if "description" in row and row["description"] is not None:
            text(row["description"], "ACP configuration description", 1000)
        result.append(ConfigOption(identifier, name, kind, current, category, choices))
    if len({option.id for option in result}) != len(result):
        raise ValueError("Duplicate ACP configuration option")
    return result


def load_state(value):
    fields(value, (), ("modes", "configOptions", "_meta"))
    modes = _modes(value["modes"]) if value.get("modes") is not None else None
    options = _config_options(value["configOptions"]) if value.get("configOptions") is not None else None
    return modes, options


def _content(value, budget=None):
    if type(value) is not dict or "type" not in value:
        raise ValueError("Invalid ACP content block")
    kind = value["type"]
    if kind == "text":
        fields(value, ("type", "text"), ("annotations", "_meta"))
        return string(value["text"], "ACP message text", 1_000_000), None
    if kind == "image":
        fields(value, ("type", "data", "mimeType"), ("uri", "annotations", "_meta"))
        data = text(value["data"], "ACP image data", MAX_BYTES * 4 // 3 + 4)
        mime = text(value["mimeType"], "ACP image MIME", 100)
        if value.get("uri") is not None:
            text(value["uri"], "ACP image URI", 4096)
        if not mime.startswith("image/"):
            return "[Image unavailable here; open the native session.]", None
        image = native_image({"type": "image", "url": "data:" + mime + ";base64," + data}, budget)
        return (None, image) if image else ("[Image unavailable here; open the native session.]", None)
    if kind == "audio":
        fields(value, ("type", "data", "mimeType"), ("annotations", "_meta"))
        text(value["data"], "ACP audio data", MAX_BYTES * 4 // 3 + 4)
        text(value["mimeType"], "ACP audio MIME", 100)
        return "[Audio available in the native session.]", None
    if kind == "resource_link":
        fields(
            value,
            ("type", "name", "uri"),
            ("annotations", "description", "mimeType", "size", "title", "_meta"),
        )
        text(value["name"], "ACP resource name", 200)
        text(value["uri"], "ACP resource URI", 4096)
        for key in ("description", "mimeType", "title"):
            if value.get(key) is not None:
                text(value[key], "ACP resource metadata", 1000)
        if value.get("size") is not None and (type(value["size"]) is not int or value["size"] < 0):
            raise ValueError("Invalid ACP resource size")
        return "[Resource available in the native session.]", None
    if kind == "resource":
        fields(value, ("type", "resource"), ("annotations", "_meta"))
        resource = value["resource"]
        if type(resource) is not dict:
            raise ValueError("Invalid ACP embedded resource")
        if "text" in resource:
            fields(resource, ("uri", "text"), ("mimeType", "_meta"))
            if resource.get("mimeType") is not None:
                text(resource["mimeType"], "ACP resource MIME", 100)
            return string(resource["text"], "ACP resource text", 1_000_000), None
        fields(resource, ("uri", "blob"), ("mimeType", "_meta"))
        text(resource["blob"], "ACP resource blob", MAX_BYTES * 4 // 3 + 4)
        if resource.get("mimeType") is not None:
            text(resource["mimeType"], "ACP resource MIME", 100)
        return "[Resource available in the native session.]", None
    raise ValueError("Unknown ACP content block")


class History:
    def __init__(self, session_id):
        self.session_id = text(session_id, "ACP session id", 1024)
        self.messages = {}
        self.activities = {}
        self.timeline = []
        self.commands = []
        self.modes = None
        self.config_options = []
        self.denied_permissions = 0
        self.update_count = 0
        self.image_budget = ImageBudget()
        self.usage = None

    def load(self, value):
        modes, options = load_state(value)
        if modes is not None:
            self.modes = modes
        if options is not None:
            self.config_options = options

    def _message(self, role, native_id, body=None, image=None):
        if native_id is None:
            native_id = "chunk-" + str(len(self.timeline) + 1)
        identifier = "acp:" + text(native_id, "ACP message id", 200)
        existing = self.messages.get(identifier)
        if existing is not None and existing.role != role:
            raise ValueError("ACP message id changed role")
        if existing is None:
            existing = Message(identifier, role, "", images=[])
            self.messages[identifier] = existing
            self.timeline.append(identifier)
        body = existing.text + (body or "")
        images = list(existing.images or [])
        if image:
            images.append(image)
        self.messages[identifier] = Message(identifier, role, body, images=images or None)

    def _tool_images(self, tool_id, content):
        if content is None:
            return
        if type(content) is not list or len(content) > 1000:
            raise ValueError("Invalid ACP tool content")
        for index, item in enumerate(content):
            if type(item) is not dict or "type" not in item:
                raise ValueError("Invalid ACP tool content item")
            if item["type"] == "content":
                fields(item, ("type", "content"), ("_meta",))
                body, image = _content(item["content"], self.image_budget)
                if body is not None or image is not None:
                    identifier = "tool-" + tool_id + "-" + str(index)
                    self._message("assistant", identifier, body, image)
            elif item["type"] == "diff":
                fields(item, ("type", "path", "newText"), ("oldText", "_meta"))
                text(item["path"], "ACP tool path", 4096)
                string(item["newText"], "ACP tool diff", 1_000_000)
                if item.get("oldText") is not None:
                    string(item["oldText"], "ACP tool diff", 1_000_000)
            elif item["type"] == "terminal":
                fields(item, ("type", "terminalId"), ("_meta",))
                text(item["terminalId"], "ACP terminal id", 200)
            else:
                raise ValueError("Unknown ACP tool content type")

    def _tool(self, kind, value):
        required = (
            ("sessionUpdate", "toolCallId", "title")
            if kind == "tool_call"
            else (
                "sessionUpdate",
                "toolCallId",
            )
        )
        optional = (
            "name",
            "title",
            "kind",
            "status",
            "content",
            "locations",
            "rawInput",
            "rawOutput",
            "_meta",
        )
        fields(value, required, optional)
        identifier = text(value["toolCallId"], "ACP tool id", 200)
        previous = self.activities.get(identifier)
        title = value.get("title")
        if title is not None:
            text(title, "ACP tool title", 200)
        elif previous is not None:
            title = previous.label
        name = value.get("name")
        if name is not None:
            text(name, "ACP tool name", 200)
        if "kind" in value and value["kind"] is not None and value["kind"] not in (
            "read", "edit", "delete", "move", "search", "execute", "think", "fetch", "switch_mode", "other",
        ):
            raise ValueError("Unknown ACP tool kind")
        if "locations" in value and value["locations"] is not None:
            locations = value["locations"]
            if type(locations) is not list or len(locations) > 1000:
                raise ValueError("Invalid ACP tool locations")
            for location in locations:
                fields(location, ("path",), ("line", "_meta"))
                text(location["path"], "ACP tool path", 4096)
                if location.get("line") is not None and (
                    type(location["line"]) is not int or location["line"] < 0
                ):
                    raise ValueError("Invalid ACP tool location")
        for key in ("rawInput", "rawOutput"):
            if key in value:
                _json_value(value[key])
        if title is None and name is None:
            raise ValueError("ACP tool update arrived before its start")
        label = text(title if title is not None else name, "ACP tool label", 200)
        status = value.get("status")
        if status is None:
            status = previous.status if previous else "observed"
        status_map = {
            "pending": "running",
            "in_progress": "running",
            "completed": "completed",
            "failed": "failed",
        }
        if status == "observed":
            mapped_status = status
        elif status in status_map:
            mapped_status = status_map[status]
        else:
            raise ValueError("Invalid ACP tool status")
        activity_id = "activity:acp:" + identifier
        self.activities[identifier] = Activity(activity_id, label, mapped_status)
        if previous is None:
            self.timeline.append(activity_id)
        self._tool_images(identifier, value.get("content"))

    def _commands(self, value):
        fields(value, ("sessionUpdate", "availableCommands"), ("_meta",))
        rows = value["availableCommands"]
        if type(rows) is not list or len(rows) > 100:
            raise ValueError("Invalid ACP command list")
        result = []
        for row in rows:
            fields(row, ("name", "description"), ("input", "_meta"))
            name = text(row["name"], "ACP command name", 100)
            if not _COMMAND.fullmatch(name):
                raise ValueError("Invalid ACP command name")
            description = text(row["description"], "ACP command description", 1000)
            input_value = row.get("input")
            hint = ""
            if input_value is not None:
                fields(input_value, ("hint",), ("_meta",))
                hint = text(input_value["hint"], "ACP command input hint", 500)
            result.append(SlashCommand(name, description, hint))
        if len({row.name for row in result}) != len(result):
            raise ValueError("Duplicate ACP command name")
        self.commands = result

    def update(self, value):
        fields(value, ("sessionId", "update"), ("_meta",))
        if value["sessionId"] != self.session_id:
            raise ValueError("ACP update belongs to another session")
        update = value["update"]
        if type(update) is not dict:
            raise ValueError("Invalid ACP session update")
        kind = update.get("sessionUpdate")
        self.update_count += 1
        if self.update_count > MAX_UPDATES:
            raise ValueError("ACP history exceeds its limit")
        if kind in ("user_message_chunk", "agent_message_chunk"):
            fields(update, ("sessionUpdate", "content"), ("messageId", "_meta"))
            native_id = update.get("messageId")
            if native_id is not None:
                text(native_id, "ACP message id", 200)
            body, image = _content(update["content"], self.image_budget)
            self._message("user" if kind == "user_message_chunk" else "assistant", native_id, body, image)
        elif kind in ("tool_call", "tool_call_update"):
            self._tool(kind, update)
        elif kind == "available_commands_update":
            self._commands(update)
        elif kind == "current_mode_update":
            fields(update, ("sessionUpdate", "currentModeId"), ("_meta",))
            current = text(update["currentModeId"], "ACP current mode", 200)
            if self.modes is not None:
                if current not in {key for key, _ in self.modes.choices}:
                    raise ValueError("ACP mode update is not an advertised choice")
                self.modes = Mode(current, self.modes.choices)
        elif kind == "config_option_update":
            fields(update, ("sessionUpdate", "configOptions"), ("_meta",))
            self.config_options = _config_options(update["configOptions"])
        elif kind in ("agent_thought_chunk", "plan", "plan_update", "plan_removed"):
            # Private reasoning and plans are intentionally not included in the chat transcript.
            if kind == "agent_thought_chunk":
                fields(update, ("sessionUpdate", "content"), ("messageId", "_meta"))
                _content(update["content"])
            elif kind == "plan":
                fields(update, ("sessionUpdate", "entries"), ("_meta",))
                if type(update["entries"]) is not list:
                    raise ValueError("Invalid ACP plan")
            elif kind == "plan_update":
                fields(update, ("sessionUpdate", "plan"), ("_meta",))
            else:
                fields(update, ("sessionUpdate", "planId"), ("_meta",))
                text(update["planId"], "ACP plan id", 200)
        elif kind == "session_info_update":
            fields(update, ("sessionUpdate",), ("title", "updatedAt", "_meta"))
            for key in ("title", "updatedAt"):
                if key in update and update[key] is not None:
                    text(update[key], "ACP session metadata", 1000)
        elif kind == "usage_update":
            fields(update, ("sessionUpdate", "used", "size"), ("cost", "_meta"))
            if any(type(update[key]) is not int or update[key] < 0 for key in ("used", "size")):
                raise ValueError("Invalid ACP context usage")
            cost = update.get("cost")
            amount, currency = None, None
            if cost is not None:
                fields(cost, ("amount", "currency"), ("_meta",))
                if type(cost["amount"]) not in (int, float) or not math.isfinite(cost["amount"]):
                    raise ValueError("Invalid ACP usage cost")
                amount = cost["amount"]
                currency = text(cost["currency"], "ACP usage currency", 10)
            self.usage = Usage(update["used"], update["size"], amount, currency)
        else:
            raise ValueError("Unsupported ACP session update")

    def page(self, cursor=None, since=None):
        if cursor and since:
            raise ValueError("Choose older history or catch-up")
        total = len(self.timeline)
        older = newer = None
        catching_up = False
        if since:
            offset, anchor = decode_cursor(since)
            self._check_anchor(offset, anchor)
            start, end = max(0, offset - 1), min(total, max(0, offset - 1) + PAGE_SIZE)
            catching_up = end < total
            newer = encode_cursor(end, self.timeline[end - 1]) if end else None
        elif cursor:
            offset, anchor = decode_cursor(cursor)
            self._check_anchor(offset, anchor)
            start, end = max(0, offset - PAGE_SIZE), offset
            older = encode_cursor(start, self.timeline[start - 1]) if start else None
            newer = encode_cursor(end, self.timeline[end - 1]) if end else None
        else:
            end = total
            start = max(0, end - PAGE_SIZE)
            older = encode_cursor(start, self.timeline[start - 1]) if start else None
            newer = encode_cursor(end, self.timeline[end - 1]) if end else None
        identifiers = set(self.timeline[start:end])
        messages = [message for message in self.messages.values() if message.id in identifiers]
        activity = [entry for entry in self.activities.values() if entry.id in identifiers]
        return messages, activity, self.timeline[start:end], older, newer, catching_up

    def _check_anchor(self, offset, anchor):
        if offset > len(self.timeline) or (offset and self.timeline[offset - 1] != anchor):
            raise ValueError("ACP history changed; reload")


def decode_cursor(raw):
    value = decode_json(raw)
    fields(value, ("offset", "anchor"))
    if type(value["offset"]) is not int or value["offset"] < 0:
        raise ValueError("Invalid ACP history offset")
    if value["offset"] == 0:
        if value["anchor"] != "":
            raise ValueError("Invalid ACP history anchor")
    else:
        text(value["anchor"], "ACP history anchor", 300)
    return value["offset"], value["anchor"]


def encode_cursor(offset, anchor):
    return json.dumps({"offset": offset, "anchor": anchor}, separators=(",", ":"))

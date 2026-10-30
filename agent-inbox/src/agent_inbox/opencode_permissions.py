"""OpenCode permission requests projected as explicit, one-time decisions."""

import json
import re

from .commands import Choice
from .forms import FormField, Forms, QuestionForm
from .models import fields, text


def _literal(value):
    fence = "`" * (1 + max((len(match[0]) for match in re.finditer(r"`+", value)), default=0))
    return fence + " " + value + " " + fence


def permission_path(identifier):
    text(identifier, "permission id", 200)
    if not identifier.startswith("per_") or any(not (c.isalnum() or c in "_-") for c in identifier):
        raise ValueError("Invalid native permission id")
    return "/permission/" + identifier


def decode_permission(value, session_id):
    fields(value, ("id", "sessionID", "action", "resources"), ("save", "metadata", "source", "message"))
    permission_path(value["id"])
    if value["sessionID"] != session_id:
        raise ValueError("Native permission belongs to a different session")
    action = text(value["action"], "permission action", 200)
    resources = value["resources"]
    if type(resources) is not list or not 1 <= len(resources) <= 100:
        raise ValueError("Invalid native permission resources")
    for resource in resources:
        text(resource, "permission resource", 4096)
    if "save" in value:
        if type(value["save"]) is not list or len(value["save"]) > 100:
            raise ValueError("Invalid native permission save rules")
        for resource in value["save"]:
            text(resource, "permission save rule", 4096)
    for key in ("metadata", "source"):
        if key in value and type(value[key]) is not dict:
            raise ValueError("Invalid native permission metadata")
    description = _literal(json.dumps(resources, ensure_ascii=False))
    if "message" in value:
        description = _literal(text(value["message"], "permission message", 16384)) + "\n\n" + description
    return QuestionForm(value["id"], "Permission: " + _literal(action), [FormField(
        "decision", "Decision", "string", required=True,
        choices=[Choice("once", "Allow once"), Choice("reject", "Deny")],
        description=description,
    )])


def read(api, path, session_id):
    value = api.call("GET", path + "/permission")
    fields(value, ("data",))
    rows = value["data"]
    if type(rows) is not list or len(rows) > 100:
        raise ValueError("Invalid native permission list")
    result = [decode_permission(row, session_id) for row in rows]
    if len({form.id for form in result}) != len(result):
        raise ValueError("Duplicate native permission ids")
    return Forms(result)

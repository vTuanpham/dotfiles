"""Project OpenCode's published Form.Info fields without parsing transcript text."""

import math

from .commands import Choice
from .forms import Condition, FormField, Forms, QuestionForm
from .models import fields, text


def form_path(identifier):
    text(identifier, "form id", 200)
    if not identifier.startswith("frm_") or any(not (c.isalnum() or c in "_-") for c in identifier):
        raise ValueError("Invalid native form id")
    return "/form/" + identifier


def decode_form(value, session_id):
    fields(value, ("id", "sessionID", "title", "fields"), ("metadata",))
    form_path(value["id"])
    if value["sessionID"] != session_id or type(value["title"]) is not str:
        raise ValueError("Native question belongs to a different session")
    if type(value["fields"]) is not list or not 1 <= len(value["fields"]) <= 50:
        raise ValueError("Invalid native question fields")
    questions, keys = [], set()
    for row in value["fields"]:
        if type(row) is not dict:
            raise ValueError("Invalid native question field")
        key = text(row["key"], "question key", 200)
        if key in keys:
            raise ValueError("Duplicate native question key")
        kind = row["type"]
        if kind not in ("string", "number", "integer", "boolean", "multiselect"):
            return QuestionForm(value["id"], value["title"], [], "Open this question in the native session.")
        for name in ("required", "custom", "hidden"):
            if name in row and type(row[name]) is not bool:
                raise ValueError("Invalid native question flag")
        choices, conditions, constraints = [], [], {}
        for option in row.get("options", []):
            fields(option, ("value", "label"), ("description",))
            if any(type(option[key]) is not str or len(option[key]) > 16384
                   or "\0" in option[key] for key in ("value", "label")):
                raise ValueError("Invalid native choice")
            choices.append(Choice(option["value"], option["label"]))
        if len({option.value for option in choices}) != len(choices):
            raise ValueError("Duplicate native choices")
        for condition in row.get("when", []):
            fields(condition, ("key", "op", "value"))
            if (condition["key"] not in keys or condition["op"] not in ("eq", "neq")
                    or type(condition["value"]) not in (str, int, float, bool)):
                raise ValueError("Invalid native visibility condition")
            if type(condition["value"]) in (int, float) and not math.isfinite(condition["value"]):
                raise ValueError("Non-finite native visibility condition")
            conditions.append(Condition(condition["key"], condition["op"], condition["value"]))
        for name in ("minimum", "maximum", "minLength", "maxLength", "minItems", "maxItems",
                     "format", "pattern", "placeholder"):
            if name not in row:
                continue
            constraint = row[name]
            if name in ("format", "pattern", "placeholder"):
                if type(constraint) is not str:
                    raise ValueError("Invalid native text constraint")
            elif type(constraint) not in (int, float) or not math.isfinite(constraint):
                raise ValueError("Invalid native numeric constraint")
            if name in ("minLength", "maxLength", "minItems", "maxItems") and (
                    type(constraint) is not int or constraint < 0):
                raise ValueError("Invalid native length constraint")
            constraints[name] = constraint
        for lower, upper in (("minimum", "maximum"), ("minLength", "maxLength"), ("minItems", "maxItems")):
            if lower in constraints and upper in constraints and constraints[lower] > constraints[upper]:
                raise ValueError("Contradictory native bounds")
        label, description = row.get("title", key), row.get("description", "")
        if type(label) is not str or type(description) is not str:
            raise ValueError("Invalid question label")
        question = FormField(key, label, kind, row.get("required", False), choices,
                             row.get("custom", False), row.get("default"), conditions,
                             constraints, description, row.get("hidden", False))
        if question.default is not None:
            question.validate(question.default)
        questions.append(question)
        keys.add(key)
    return QuestionForm(value["id"], value["title"], questions)


def read(api, path, session_id):
    value = api.call("GET", path + "/form")
    fields(value, ("data",))
    if type(value["data"]) is not list:
        raise ValueError("Invalid native question list")
    result = [decode_form(row, session_id) for row in value["data"]]
    if len({form.id for form in result}) != len(result):
        raise ValueError("Duplicate native questions")
    return Forms(result)

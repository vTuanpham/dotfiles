"""Typed questions and answers shared by native adapters."""

import math
from dataclasses import dataclass, field

from .commands import Choice
from .models import DeliveryRejected, NoLongerPending

Value = str | int | float | bool | list[str]


@dataclass(frozen=True)
class Condition:
    key: str
    op: str
    value: str | int | float | bool


@dataclass(frozen=True)
class FormField:
    key: str
    label: str
    kind: str
    required: bool = False
    choices: list[Choice] = field(default_factory=list)
    custom: bool = False
    default: Value | None = None
    when: list[Condition] = field(default_factory=list)
    constraints: dict[str, str | int | float] = field(default_factory=dict)
    description: str = ""
    hidden: bool = False

    def active(self, answer):
        for condition in self.when:
            if condition.key not in answer:
                return False
            value = answer[condition.key]
            if type(value) is list:
                equal = condition.value in value
            else:
                numeric = type(value) in (int, float) and type(condition.value) in (int, float)
                equal = (numeric or type(value) is type(condition.value)) and value == condition.value
            if equal != (condition.op == "eq"):
                return False
        return True

    def validate(self, value):
        valid = {
            "string": type(value) is str,
            "boolean": type(value) is bool,
            "integer": type(value) in (int, float) and math.isfinite(value) and value == int(value),
            "number": type(value) in (int, float),
            "multiselect": type(value) is list and all(type(item) is str for item in value),
        }.get(self.kind, False)
        if not valid:
            raise DeliveryRejected("Answer has the wrong type")
        if type(value) in (int, float):
            if not math.isfinite(value):
                raise DeliveryRejected("Answer must be finite")
            if ("minimum" in self.constraints and value < self.constraints["minimum"]
                    or "maximum" in self.constraints and value > self.constraints["maximum"]):
                raise DeliveryRejected("Answer is outside the native bounds")
        if type(value) in (str, list):
            minimum = self.constraints.get("minLength" if type(value) is str else "minItems", 0)
            maximum = self.constraints.get("maxLength" if type(value) is str else "maxItems", 16384)
            if not minimum <= len(value) <= min(maximum, 16384):
                raise DeliveryRejected("Answer length is outside the native bounds")
        if self.kind == "multiselect" and len(value) != len(set(value)):
            raise DeliveryRejected("Duplicate choices")
        if self.choices and not self.custom:
            options = {choice.value for choice in self.choices}
            if any(item not in options for item in (value if type(value) is list else [value])):
                raise DeliveryRejected("Answer is not a native choice")


@dataclass(frozen=True)
class QuestionForm:
    id: str
    title: str
    fields: list[FormField]
    unavailable: str = ""

    def validate(self, answer):
        if self.unavailable or type(answer) is not dict or answer.keys() - {f.key for f in self.fields}:
            raise DeliveryRejected("Unsupported question or answer fields")
        for question in self.fields:
            active = question.active(answer)
            if not active and question.key in answer:
                raise DeliveryRejected("Inactive questions cannot be answered")
            if active and question.required and question.key not in answer:
                raise DeliveryRejected("A required answer is missing")
            if question.key in answer:
                question.validate(answer[question.key])


@dataclass(frozen=True)
class Forms:
    forms: list[QuestionForm]
    unavailable: str = ""

    def selected(self, identifier):
        found = [form for form in self.forms if form.id == identifier]
        if not found:
            raise NoLongerPending("Question is no longer pending in this session")
        if len(found) != 1:
            raise DeliveryRejected("Ambiguous native question identity")
        return found[0]


def forms(provider, target):
    read = getattr(provider, "forms", None)
    if read is None:
        return Forms([], "This connection cannot relay its pending native questions.")
    return read(target)

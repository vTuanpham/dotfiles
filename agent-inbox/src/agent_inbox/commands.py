"""Shared, typed controls; adapters own native command discovery and execution."""

from dataclasses import dataclass
from typing import Literal

from .models import DeliveryRejected, text


@dataclass(frozen=True)
class Choice:
    value: str
    label: str


@dataclass(frozen=True)
class Command:
    id: str
    label: str
    kind: Literal["select", "text", "action"]
    choices: list[Choice] | None = None
    current: str | None = None
    description: str = ""

    def validate(self, value):
        if type(value) is not str or len(value) > 16384 or "\0" in value:
            raise DeliveryRejected("Invalid command value")
        if self.kind == "select" and value not in {choice.value for choice in self.choices or []}:
            raise DeliveryRejected("Choose a native option")
        if self.kind == "action" and value:
            raise DeliveryRejected("This action has no arguments")


@dataclass(frozen=True)
class Commands:
    controls: list[Command]
    unavailable: str = ""

    def selected(self, identifier, value):
        text(identifier, "command id", 200)
        choices = [command for command in self.controls if command.id == identifier]
        if len(choices) != 1:
            raise DeliveryRejected("This session does not expose that command")
        choices[0].validate(value)
        return choices[0]


def catalog(provider, target):
    discover = getattr(provider, "commands", None)
    if discover is None:
        return Commands([], "This connection does not expose native commands.")
    return discover(target)

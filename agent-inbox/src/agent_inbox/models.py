import json
import math
from dataclasses import asdict, dataclass
from typing import Literal, Protocol
from urllib.parse import urlsplit


class PairingError(PermissionError):
    pass


class DeliveryRejected(ValueError):
    pass


def decode_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON field")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError("Non-finite JSON value")

    def finite(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("Non-finite JSON value")
        return number

    return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid_constant, parse_float=finite)


def text(value, name, maximum=16384):
    if type(value) is not str or not value.strip() or len(value) > maximum or "\0" in value:
        raise ValueError(f"Invalid {name}")
    return value


def fields(value, required, optional=()):
    if (type(value) is not dict or not set(required) <= value.keys()
            or value.keys() - set(required) - set(optional)):
        raise ValueError("Missing or unknown fields")
    return value


def https_url(value):
    text(value, "native session URL", 4096)
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or any(c.isspace() or ord(c) < 32 for c in value)):
        raise ValueError("Native session links require HTTPS without embedded credentials")
    parsed.port
    return value


@dataclass(frozen=True)
class Target:
    id: str
    adapter: str
    harness: str
    session_id: str
    label: str
    settings: dict

    @classmethod
    def decode(cls, value):
        fields(value, ("id", "adapter", "harness", "session_id", "label", "settings"))
        for name in ("id", "adapter", "harness", "session_id", "label"):
            text(value[name], name, 200)
        if type(value["settings"]) is not dict:
            raise ValueError("Invalid adapter settings")
        return cls(**value)

    def public(self):
        return {key: getattr(self, key) for key in ("id", "harness", "label")}


@dataclass(frozen=True)
class Answer:
    question: str
    answer: str


@dataclass(frozen=True)
class Message:
    id: str
    role: Literal["user", "assistant"]
    text: str
    phase: Literal["commentary", "partial_answer", "final_answer"] | None = None
    answers: list[Answer] | None = None
    images: list[str] | None = None


@dataclass(frozen=True)
class Outgoing:
    id: str
    text: str
    images: list[str]


@dataclass(frozen=True)
class RootInfo:
    session_id: str
    label: str
    status: str
    saved: bool = False


@dataclass(frozen=True)
class Activity:
    id: str
    label: str
    status: str
    duration_ms: int | float | None = None
    started_at_ms: int | float | None = None


@dataclass(frozen=True)
class Snapshot:
    status: str
    can_send: bool
    messages: list[Message]
    older_cursor: str | None = None
    native_url: str | None = None
    newer_cursor: str | None = None
    catching_up: bool = False
    activity: list[Activity] | None = None
    timeline: list[str] | None = None

    def json(self):
        return asdict(self)


class Adapter(Protocol):
    def discover(self, seed: Target) -> list[RootInfo] | None: ...

    def snapshot(self, target: Target, cursor: str | None = None, since: str | None = None) -> Snapshot: ...

    def send(self, target: Target, message: Outgoing) -> Literal["queued", "steered", "forwarded"]: ...

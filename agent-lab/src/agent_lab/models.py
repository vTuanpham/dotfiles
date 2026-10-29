"""The private registry's versioned boundary; never guess missing provenance."""

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

ID = re.compile(r"[a-z0-9][a-z0-9-]{0,47}-[a-f0-9]{12}\Z")


def text(value: object, limit: int, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > limit or "\x00" in value:
        raise ValueError("invalid registry text")
    return value


def timestamp(value: object) -> datetime:
    text(value, 64)
    assert isinstance(value, str)
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("registry timestamps require a timezone")
    return parsed


def fields(value: object, expected: set[str]) -> dict:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("invalid registry fields")
    return value


@dataclass(frozen=True)
class Actor:
    harness: str | None
    session: str | None
    model: str | None
    effort: str | None
    cwd: str
    repository: str | None
    branch: str | None
    commit: str | None

    @classmethod
    def decode(cls, value: object) -> "Actor":
        data = fields(value, set(cls.__dataclass_fields__))
        for key, limit in (
            ("harness", 64),
            ("session", 256),
            ("model", 128),
            ("effort", 32),
            ("repository", 4096),
            ("branch", 256),
            ("commit", 64),
        ):
            text(data[key], limit, nullable=True)
        text(data["cwd"], 4096)
        for key in ("cwd", "repository"):
            if data[key] is not None and not Path(data[key]).is_absolute():
                raise ValueError("registry origin paths must be absolute")
        return cls(**data)


@dataclass(frozen=True)
class Run:
    actor: Actor
    started_at: str
    finished_at: str | None
    exit_code: int | None

    @classmethod
    def decode(cls, value: object) -> "Run":
        data = fields(value, set(cls.__dataclass_fields__)).copy()
        data["actor"] = Actor.decode(data["actor"])
        start = timestamp(data["started_at"])
        finish = timestamp(data["finished_at"]) if data["finished_at"] is not None else None
        code = data["exit_code"]
        if code is not None and (type(code) is not int or not 0 <= code <= 255):
            raise ValueError("invalid registry exit code")
        if (finish is None) != (code is None) or (finish is not None and finish < start):
            raise ValueError("inconsistent registry run")
        return cls(**data)


@dataclass(frozen=True)
class Record:
    schema: int
    id: str
    purpose: str
    created_at: str
    updated_at: str
    created_by: Actor
    last_run: Run | None = None
    retired_at: str | None = None
    purge_after: str | None = None
    kept: bool = False
    summary: str | None = None

    @property
    def state(self) -> str:
        return "kept" if self.kept else "retired" if self.retired_at else "active"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def decode(cls, value: object) -> "Record":
        data = fields(value, set(cls.__dataclass_fields__)).copy()
        if type(data["schema"]) is not int or data["schema"] != 1:
            raise ValueError("unsupported registry schema")
        if not isinstance(data["id"], str) or not ID.fullmatch(data["id"]):
            raise ValueError("invalid workspace ID")
        text(data["purpose"], 2000)
        text(data["summary"], 4000, nullable=True)
        created, updated = timestamp(data["created_at"]), timestamp(data["updated_at"])
        retired = timestamp(data["retired_at"]) if data["retired_at"] is not None else None
        purge = timestamp(data["purge_after"]) if data["purge_after"] is not None else None
        if updated < created or (retired is None) != (purge is None):
            raise ValueError("inconsistent registry dates")
        if retired is not None and (purge is None or retired < created or purge <= retired):
            raise ValueError("invalid retirement period")
        if type(data["kept"]) is not bool or (data["kept"] and retired is not None):
            raise ValueError("invalid kept state")
        data["created_by"] = Actor.decode(data["created_by"])
        if data["last_run"] is not None:
            data["last_run"] = Run.decode(data["last_run"])
        return cls(**data)


def decode_json(raw: str) -> object:
    def pairs(items: list[tuple[str, object]]) -> dict:
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate registry field")
            result[key] = value
        return result

    def constant(value: str) -> None:
        raise ValueError("non-finite registry value")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def load(raw: str) -> Record:
    return Record.decode(decode_json(raw))

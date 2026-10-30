"""Account observations preserve source, account and freshness separately."""

import json
import re
from dataclasses import dataclass
from datetime import datetime


def loads(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON field")
            result[key] = value
        return result

    def invalid(_):
        raise ValueError("non-finite JSON value")

    return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)


def timestamp(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", value
    ):
        raise ValueError("timestamp requires RFC3339 date, time and timezone")
    return datetime.fromisoformat(value).timestamp()


@dataclass(frozen=True)
class QuotaWindow:
    label: str
    remaining_percent: int
    group: str
    limit: str
    resets: str | None


@dataclass(frozen=True)
class Quota:
    backend: str
    account: str
    plan: str | None
    active: bool
    windows: tuple[QuotaWindow, ...]
    status: str | None
    observed_at: str | None
    age_seconds: int | None
    freshness: str

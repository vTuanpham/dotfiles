"""Private, selected-session telemetry. Unknown values stay unknown."""

import time
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Account:
    identity: str | None
    email: str | None
    plan: str | None
    scope: str


@dataclass(frozen=True)
class Quota:
    label: str
    used_percent: int
    window_minutes: int | None
    resets_at: int | None


@dataclass(frozen=True)
class Metric:
    label: str
    value: int | float
    unit: str


@dataclass(frozen=True)
class Worker:
    id: str
    label: str
    status: str
    model: str | None = None


@dataclass(frozen=True)
class Tool:
    name: str
    status: str
    tool_count: int | None = None


@dataclass
class SessionContext:
    account: Account | None = None
    quotas: list[Quota] = field(default_factory=list)
    metrics: list[Metric] = field(default_factory=list)
    workers: list[Worker] = field(default_factory=list)
    tools: list[Tool] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)
    fetched_at: int = field(default_factory=lambda: int(time.time()))


def context(provider, target):
    read = getattr(provider, "context", None)
    if read is None:
        return SessionContext(notices=["This connection does not expose session details."])
    return read(target)

"""Version 1 public status contract. Only status.Collector produces snapshots."""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Assessment:
    state: str
    reason: str
    quiet_seconds: int
    threshold_seconds: int
    recent_step_seconds: int | None = None
    usual_step_seconds: int | None = None
    activity_age_seconds: int | None = None
    waiting_on_job: str | None = None
    notice_id: str | None = None


@dataclass(frozen=True)
class DeclaredWait:
    kind: str
    note: str
    declared_at: str
    expected_seconds: int
    peer: str | None = None


@dataclass(frozen=True)
class InFlight:
    id: str
    kind: str
    started_at: str
    age_seconds: int


@dataclass(frozen=True)
class Event:
    id: str
    job: str
    offset: int
    kind: str
    at: str | None
    text: str
    status: str
    error: str
    wakes: bool
    informational: bool


@dataclass(frozen=True)
class PeerMessage:
    id: str
    source: str
    target: str
    at: str
    kind: str
    size: int
    preview: str | None


@dataclass(frozen=True)
class PeerEdge:
    id: str
    source: str
    target: str
    count: int
    last_at: str
    last_kind: str


@dataclass(frozen=True)
class Peers:
    nodes: tuple[str, ...]
    edges: tuple[PeerEdge, ...]
    recent_messages: tuple[PeerMessage, ...]
    window_seconds: int = 86400
    message_limit: int = 100


@dataclass(frozen=True)
class HeavyRequest:
    id: str
    job: str | None
    command: str | None
    need_bytes: int
    exclusive: bool
    state: str
    age_seconds: int
    started_at: str | None
    alive: bool


@dataclass(frozen=True)
class HeavyQueue:
    requests: tuple[HeavyRequest, ...]
    paused: bool
    pause_reason: str | None
    reserved_bytes: int
    budget_bytes: int | None
    error: str | None = None


@dataclass(frozen=True)
class GroupPressure:
    id: str
    memory_bytes: int | None
    memory_max_bytes: int | None
    oom_kill: int | None
    oom_kill_delta: int | None
    attributed_job: str | None
    cpu_quota: float | None
    usage_usec: int | None
    throttled_usec: int | None
    cpu_fraction: float | None
    throttled: bool


@dataclass(frozen=True)
class HostPressure:
    available_bytes: int | None
    total_bytes: int | None
    load1: float | None
    headroom_bytes: int | None
    groups: tuple[GroupPressure, ...]
    warning: str
    error: str | None = None


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


@dataclass(frozen=True)
class Job:
    id: str
    owner: str
    name: str
    title: str
    backend: str | None
    account: str | None
    model: str | None
    effort: str | None
    cwd: str | None
    directory: str
    running: bool
    state: str
    reason: str
    last_event_at: str | None
    last_event_age_seconds: int | None
    stall: Assessment
    memory_cap: str
    cpu_cap: str
    memory_bytes: int | None
    cpu_seconds: float | None
    oom_kill: int | None
    oom_kill_delta: int | None
    message_count: int
    last_message: str | None
    started_at: str | None
    finished_at: str | None
    awaiting_root: bool
    unanswered_urgent: int
    retry_attempt: int | None
    retry_maximum: int | None
    now_doing: str | None
    retired_at: str | None
    purge_after: str | None
    log_identity: str
    acknowledged_through: int
    completed_through: int
    group: str | None = None
    waiting: DeclaredWait | None = None
    in_flight: InFlight | None = None


@dataclass(frozen=True)
class Owner:
    id: str
    jobs: int
    running: int
    unanswered_urgent: int
    size_bytes: int | None
    last_root_command: str | None
    root_backend: str | None = None
    root_session_id: str | None = None
    active_watch: bool = False


@dataclass(frozen=True)
class WakePolicy:
    wake: str = "each"
    settle_seconds: int = 60
    remind_seconds: int | None = 900
    max_wait_seconds: int | None = None
    repeat_reminders: bool = False


@dataclass(frozen=True)
class GroupNotice(Event):
    owner: str
    group: str | None
    jobs: tuple[str, ...]
    missing: tuple[str, ...]
    completion_ids: tuple[str, ...]
    seen: bool


@dataclass(frozen=True)
class WakeGroup:
    id: str
    owner: str
    name: str | None
    policy: WakePolicy
    members: tuple[str, ...]
    done: int
    total: int
    held_completions: tuple[str, ...]
    next_reminder_at: str | None
    settle_due_at: str | None
    max_wait_due_at: str | None


@dataclass(frozen=True)
class TidyItem:
    kind: str
    path: str
    owner: str
    name: str
    bytes: int
    age_days: int
    is_dirty: bool | None


@dataclass(frozen=True)
class Retention:
    retired: int
    expired: int
    eligible: int | None
    dirty: int | None
    reclaim_bytes: int | None
    items: tuple[TidyItem, ...]
    scanned: bool
    archive_path: str


@dataclass(frozen=True)
class Dependency:
    source: str
    target: str
    reason: str


@dataclass(frozen=True)
class Snapshot:
    schema_version: int
    generated_at: str
    jobs: tuple[Job, ...]
    owners: tuple[Owner, ...]
    wake_events: tuple[Event, ...]
    events: tuple[Event, ...]
    heavy: HeavyQueue
    pressure: HostPressure
    quotas: tuple[Quota, ...]
    retention: Retention
    peers: Peers
    dependencies: tuple[Dependency, ...]
    errors: tuple[str, ...]
    schema_minor: int = 2
    groups: tuple[WakeGroup, ...] = ()
    group_events: tuple[GroupNotice, ...] = ()
    unacknowledged_completions: int = 0
    oldest_unacknowledged_completion_age_seconds: int | None = None

    def to_dict(self):
        return asdict(self)

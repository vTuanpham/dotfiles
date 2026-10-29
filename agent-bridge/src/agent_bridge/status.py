"""The sole status producer. Commands and harnesses render its versioned snapshot."""

import math
import os
import re
import subprocess
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from . import (
    core,
    groups,
    heavy,
    owner_binding,
    peers,
    resources,
    status_observations,
    status_resources,
    waiting,
)
from .acknowledgements import cursor_for, read_owner
from .assessment import BUSY_WINDOW, SILENCE_SECONDS, assess
from .core import job_caps, tree_size
from .status_activity import (
    NON_ACTIVITY_KINDS,
    busy,
    in_flight,
    pace,
    running,
    socket_bytes,
    tree_cpu,
)
from .status_inputs import EventLog, quotas, read_job, tidy, timestamp, unanswered
from .status_model import (
    Dependency,
    DirectMessage,
    GroupPressure,
    HeavyQueue,
    HeavyRequest,
    HostPressure,
    Job,
    Owner,
    PeerEdge,
    Peers,
    Retention,
    Snapshot,
)

DIRECT_MESSAGE_WINDOW_SECONDS = 86_400
DIRECT_MESSAGE_LIMIT = 100
_STEER_FILE = re.compile(r"[0-9]+\.md\Z")


def _legacy_peer_message(raw: dict, text: str, owner: str) -> bool:
    if raw.get("peerDirected") is True:
        return True
    if raw.get("peerDirected") is False:
        return False
    head, separator, _body = text.partition(":")
    if not separator or not head.upper().startswith("TO "):
        return False
    recipients = [name.strip().lower() for name in head[3:].split(",")]
    return bool(recipients) and all(
        name not in {"root", "coordinator", owner.lower()} for name in recipients
    )


def _message_fields(raw: dict, text: str) -> tuple[int | None, str | None]:
    if "preview" in raw or "size" in raw:
        preview = raw.get("preview")
        return raw.get("size"), peers.preview(preview) if isinstance(preview, str) else None
    # Legacy logs have no indication that a preview was scrubbed in the worker's environment.
    return (len(text.encode("utf-8")) if text else None), None


def _direct_messages(owner: str, identifier: str, rows, now: float) -> list[DirectMessage]:
    sent = {
        raw.get("file"): (raw, event)
        for raw, event in rows
        if raw.get("kind") == "steer_sent"
        and type(raw.get("file")) is str
        and _STEER_FILE.fullmatch(raw["file"])
    }
    result = []

    def add(
        event, source, target, direction, kind, *, at=None, recorded_at=None,
        message_id=None, size=None, preview=None,
    ):
        at = event.at if at is None else at
        if at is None:
            return
        recorded_at = recorded_at or at
        age = now - timestamp(recorded_at)
        if not 0 <= age <= DIRECT_MESSAGE_WINDOW_SECONDS:
            return
        result.append(
            DirectMessage(
                event.id if message_id is None else message_id,
                source,
                target,
                direction,
                at,
                kind,
                size,
                preview,
                recorded_at,
            )
        )

    for raw, event in rows:
        kind = raw["kind"]
        if kind in {"message", "question"}:
            if kind == "message" and _legacy_peer_message(raw, event.text, owner):
                continue
            size, preview = _message_fields(raw, event.text)
            add(
                event,
                identifier,
                f"root/{owner}",
                "worker_to_root",
                kind,
                size=size,
                preview=preview,
            )
        elif kind == "root_steer":
            filename = raw.get("file")
            delivery = sent.get(filename) if type(filename) is str else None
            # make_steer allocates across queued and sent files, so this basename binds the
            # delivery even if a fast runner logs steer_sent before the CLI logs root_steer.
            if delivery is None:
                continue
            delivered_raw, delivered = delivery
            add(
                event,
                f"root/{owner}",
                identifier,
                "root_to_worker",
                "steer",
                at=delivered.at or event.at,
                size=delivered_raw.get("size"),
                preview=peers.preview(delivered_raw["preview"])
                if isinstance(delivered_raw.get("preview"), str)
                else None,
            )
        elif kind == "root_prompt":
            add(
                event,
                f"root/{owner}",
                identifier,
                "root_to_worker",
                "prompt",
                recorded_at=raw.get("recorded_at"),
                size=raw.get("size"),
                preview=peers.preview(raw["preview"])
                if isinstance(raw.get("preview"), str)
                else None,
            )
    return result


def collect_host(previous=None):
    rows, requests = [], []
    paused = {"reason": None}
    queue_error = None
    try:
        if heavy.directory().exists():
            folder = heavy.prepare()
            with heavy.gate(folder):
                rows = heavy.entries(folder)
                paused = heavy.pause_state(folder)
        now = time.monotonic_ns()
        for path, row in rows:
            state = "running" if row["running"] else "queued"
            if (row.get("control") or {}).get("cancelled"):
                state = "cancelling"
            age = (
                max(0, now - row["started_ns"])
                if row["running"] and row.get("started_ns") is not None
                else heavy.waited_ns(row, paused, now)
            ) // 10**9
            requests.append(
                HeavyRequest(
                    path.stem.rsplit("-", 1)[-1][:12],
                    row.get("job") or None,
                    row.get("command"),
                    row["need"],
                    row["exclusive"],
                    state,
                    age,
                    row.get("started_at"),
                    True,
                )
            )
    except (OSError, ValueError, KeyError, RuntimeError):
        queue_error = "heavy queue unavailable; admission fails closed"
    reserved = sum(r.need_bytes for r in requests if r.state == "running")
    try:
        sample = resources.pressure(previous)
        policy = resources.limits(sample)
        before = {g.path: g for g in previous.groups} if previous else {}
        groups = []
        for g in sample.groups:
            old = before.get(g.path)
            delta = (
                max(0, g.oom_kill - old.oom_kill)
                if old and old.oom_kill is not None and g.oom_kill is not None
                else None
            )
            groups.append(
                GroupPressure(
                    str(g.path),
                    g.current,
                    g.maximum,
                    g.oom_kill,
                    delta,
                    None,
                    g.cpus,
                    g.usage_usec,
                    g.throttled_usec,
                    g.cpu_fraction,
                    g.throttled,
                )
            )
        host = HostPressure(
            sample.available,
            sample.total,
            sample.load,
            sample.shared_headroom,
            tuple(groups),
            resources.wait_reason(sample, policy, shared=True),
        )
        budget = max(0, sample.shared_capacity - policy.available)
    except (OSError, ValueError, KeyError, IndexError, RuntimeError):
        sample, budget = None, None
        host = HostPressure(
            None, None, None, None, (), "pressure unavailable; admission fails closed", "pressure unavailable"
        )
    return (
        host,
        HeavyQueue(
            tuple(requests), paused["reason"] is not None, paused["reason"], reserved, budget, queue_error
        ),
        sample,
    )


class Collector:
    """One observation per source per poll. Reuse for incremental logs and CPU/OOM deltas."""

    def __init__(self, jobs_root=None, warmup=False):
        self.root = jobs_root if jobs_root is not None else core.JOBS
        self.warmup = warmup
        self.logs = {}
        self.samples, self.busy_at, self.first_seen = {}, {}, {}
        self.processes = {}
        self.host_sample = None
        self.host_at = None
        self.host = self.queue = None

    def collect(self, owners=None, stall_min=SILENCE_SECONDS // 60, include_quotas=True, storage=False):
        now = time.time()
        self.observed_at = now
        errors, jobs, wake, recent, messages, direct_messages, retired_items = [], [], [], [], [], [], []
        retired = expired = 0
        all_events = []
        scope_jobs, job_scopes = {}, {}
        if self.host_at is None or now - self.host_at >= 10:
            self.host, self.queue, self.host_sample = collect_host(self.host_sample)
            self.host_at = now
        host, queue = self.host, self.queue
        states = []
        caller = os.environ.get("AGENT_BRIDGE_JOB") if os.environ.get(core.WORKER_FLAG) else None
        if os.environ.get(core.WORKER_FLAG) and (not caller or len(caller.split("/")) != 2):
            raise RuntimeError("worker status requires AGENT_BRIDGE_JOB")
        state_paths = sorted(self.root.glob("*/*/state.json"))
        retained_jobs = {f"{p.parent.parent.name}/{p.parent.name}" for p in state_paths}
        for path in state_paths:
            job = path.parent
            identifier = f"{job.parent.name}/{job.name}"
            if caller and job.parent.name != caller.split("/")[0]:
                continue
            if owners and not any(o in (job.parent.name, identifier) for o in owners):
                continue
            try:
                states.append((job, read_job(job, self.root)))
            except (OSError, ValueError, RuntimeError):
                errors.append(f"{identifier}: invalid or unreadable state")
        nodes = {f"{j.parent.name}/{j.name}" for j, _ in states}
        live = {f"{j.parent.name}/{j.name}": running(s) for j, s in states}
        running_jobs = {identifier for identifier, alive in live.items() if alive}
        for job, state in states:
            identifier = f"{job.parent.name}/{job.name}"
            try:
                alive = live[identifier]
                if (job.parent / "ack.json").is_symlink():
                    raise ValueError("unsafe acknowledgement file")
                cursor = cursor_for(job, read_owner(job.parent))
                identity = cursor["log"]
                size = (job / "live.jsonl").stat().st_size if identity else 0
                cached = self.logs.get(identifier)
                if cached is None or cached.identity != identity or cached.offset > size:
                    cached = EventLog(identifier, identity)
                    self.logs[identifier] = cached
                cached.read(job, errors)
                evs = [raw for raw, _ in cached.rows]
                events = [e for _, e in cached.rows]
                direct_messages.extend(_direct_messages(job.parent.name, identifier, cached.rows, now))
                if not state.get("retiredAt"):
                    all_events.extend(events)
                pending = [
                    e
                    for e in events
                    if e.informational
                    and e.offset > cursor["through"]
                    and not (e.kind == "turn_completed" and e.offset <= cursor["completed"])
                ]
                wake.extend(e for e in pending if e.wakes)
                # Keep pending info as well as the bounded timeline: watch cannot lose an unseen event.
                seen = {e.id for e in pending}
                recent.extend(pending + [e for e in events[-100:] if e.id not in seen])
                for raw, event in cached.rows:
                    if raw["kind"] == "peer_sent":
                        try:
                            message = peers.decode(raw, event.id, identifier, nodes)
                            if message and 0 <= now - timestamp(message.at) <= 86400:
                                messages.append(message)
                        except (ValueError, TypeError):
                            errors.append(f"{identifier}: invalid peer event")
                last = evs[-1] if evs else {}
                substantive = next(
                    (
                        e
                        for e in reversed(evs)
                        if e["kind"] not in NON_ACTIVITY_KINDS
                    ),
                    {},
                )
                at = substantive.get("at")
                age = max(0, int(now - timestamp(at))) if at else None
                quiet = (
                    age
                    if age is not None
                    else max(0, int(now - (job / "live.jsonl").stat().st_mtime))
                    if identity
                    else 0
                )
                if last.get("kind") == "stalled" and type(last.get("quietSeconds")) is int:
                    quiet = max(quiet, last["quietSeconds"])
                self.first_seen.setdefault(identifier, now)
                if not alive:
                    self.first_seen.pop(identifier, None)
                elif self.warmup:
                    quiet = min(quiet, int(now - self.first_seen[identifier]))
                mode, reason = ("running", "runner alive") if alive else ("idle", "no live runner")
                requests = [r for r in queue.requests if r.job == identifier and r.state == "queued"]
                retry = state.get("retry")
                unhandled = unanswered(job, evs)
                if requests:
                    mode, reason = (
                        ("paused", f"paused by root: {queue.pause_reason}")
                        if queue.paused
                        else ("waiting_for_heavy", "waiting for heavy slot")
                    )
                elif alive and (retry or substantive.get("kind") in {"retry_wait", "retryable_error"}):
                    mode, reason = "retrying", "retry backoff; same session and model"
                elif alive and unhandled and any(e.kind == "question" for e in pending):
                    mode, reason = "blocked_on_question", "waiting for question answer"
                elif alive and substantive.get("kind") == "root_wait":
                    mode, reason = "waiting_for_root", "waiting for root"
                if state.get("retiredAt"):
                    retired += 1
                    mode, reason = "retired", "retired; retained until explicit purge"
                    if timestamp(state["purgeAfter"]) <= now:
                        expired += 1
                        if storage and not alive:
                            retired_items.extend(tidy(job, state, now))
                if mode in {
                    "waiting_for_heavy",
                    "paused",
                    "retrying",
                    "waiting_for_root",
                    "blocked_on_question",
                }:
                    self.first_seen[identifier] = now
                cpu = memory = None
                if alive and (
                    identifier not in self.samples or now - self.samples[identifier][0] >= BUSY_WINDOW
                ):
                    tree = tree_cpu(state.get("runnerPid"))
                    if tree:
                        sample = (now, tree[0], socket_bytes(tree[1]))
                        if identifier in self.samples and busy(self.samples[identifier], sample):
                            self.busy_at[identifier] = now
                        self.samples[identifier] = sample
                        self.processes[identifier] = tree[1]
                if alive and identifier in self.samples:
                    cpu = self.samples[identifier][1]
                    pids = self.processes.get(identifier, set())
                    memory = status_resources.memory(pids)
                    job_scopes[identifier] = status_resources.scopes(pids)
                    for scope in job_scopes[identifier]:
                        scope_jobs.setdefault(scope, set()).add(identifier)
                working = now - self.busy_at.get(identifier, -math.inf) <= 2 * BUSY_WINDOW
                declaration = None
                if "waiting" in state:
                    try:
                        declaration = waiting.decode(state["waiting"], job.parent.name, now)
                    except (ValueError, TypeError):
                        errors.append(f"{identifier}: invalid waiting declaration")
                flight = in_flight(cached.rows, now) if alive else None
                reported = {e.get("noticeId") for e in evs
                            if e["kind"] in {"long_command", "overdue_wait"}}
                critical = any(e.wakes and e.kind != "turn_completed" or e.error
                               or e.status.lower() == "failed" for e in pending)
                assessment = assess(
                    mode, reason, quiet, stall_min * 60, working, pace(evs), waiting=declaration,
                    in_flight=flight, now=now,
                    declared_at=timestamp(declaration.declared_at) if declaration else None,
                    peer_running=bool(declaration and declaration.peer in running_jobs),
                    critical=critical, reported=reported)
                if queue.error and mode == "running":
                    assessment = replace(
                        assessment,
                        state="unknown",
                        reason=queue.error,
                        recent_step_seconds=None,
                        usual_step_seconds=None,
                    )
                caps = job_caps(state)
                completed = [e for e in events if e.kind == "turn_completed"]
                started = [e for e in events if e.kind == "turn_started"]
                last_msg = next((e.text for e in reversed(events) if e.kind == "message"), None)
                stage = next(
                    (
                        e["kind"]
                        for e in reversed(evs)
                        if e["kind"] in {"command_start", "command_end", "turn_started", "turn_completed"}
                    ),
                    None,
                )
                doing = (
                    {"command_start": "tool", "command_end": "between_tools", "turn_started": "turn"}.get(
                        stage
                    )
                    if alive and mode == "running"
                    else None
                )
                jobs.append(
                    Job(
                        identifier,
                        job.parent.name,
                        job.name,
                        state.get("title") or "",
                        state.get("backend"),
                        state.get("account"),
                        state.get("model"),
                        state.get("effort"),
                        state.get("cwd"),
                        str(job),
                        alive,
                        mode,
                        reason,
                        at,
                        age,
                        assessment,
                        caps["memoryMax"],
                        caps["cpuQuota"],
                        memory,
                        cpu,
                        None,
                        None,
                        sum(e.kind == "message" for e in events),
                        last_msg,
                        started[-1].at if started else None,
                        completed[-1].at if completed else None,
                        any(e.kind == "turn_completed" for e in pending),
                        unhandled,
                        retry["attempt"] if retry else None,
                        retry["maximum"] if retry else None,
                        doing,
                        state.get("retiredAt"),
                        state.get("purgeAfter"),
                        identity,
                        cursor["through"],
                        cursor["completed"],
                        waiting=declaration,
                        in_flight=flight,
                    )
                )
            except (OSError, ValueError, TypeError, KeyError, RuntimeError, subprocess.SubprocessError):
                errors.append(f"{identifier}: status unavailable")
        # A root filtering its text view still needs to rule out other runners sharing a scope.
        if owners and not caller and scope_jobs:
            visible = {j.id for j in jobs}
            for path in state_paths:
                identifier = f"{path.parent.parent.name}/{path.parent.name}"
                if identifier in visible:
                    continue
                try:
                    state = read_job(path.parent, self.root)
                    tree = tree_cpu(state.get("runnerPid")) if running(state) else None
                    if tree:
                        for scope in status_resources.scopes(tree[1]):
                            if scope in scope_jobs:
                                scope_jobs[scope].add(identifier)
                except (OSError, ValueError, RuntimeError):
                    errors.append("scope ownership unavailable")
                    scope_jobs.clear()
                    break
        metrics = {}
        pressure_groups = list(host.groups)
        for scope, identifiers in scope_jobs.items():
            if len(identifiers) != 1 or caller:
                continue  # a shared scope cannot attribute an OOM to one job
            identifier = next(iter(identifiers))
            try:
                memory, oom = status_resources.scope_memory(scope)
                metrics.setdefault(identifier, []).append(memory)
                pressure_groups.append(
                    GroupPressure(
                        str(scope), memory, None, oom, None, identifier, None, None, None, None, False
                    )
                )
            except (OSError, ValueError, KeyError):
                errors.append(f"{identifier}: scope counters unavailable")
        pressure_groups = tuple({g.id: g for g in pressure_groups}.values())
        try:
            pressure_groups, totals, changes = status_observations.observe(
                self.root.parent / "status", pressure_groups, retained_jobs
            )
        except (OSError, ValueError, TypeError):
            errors.append("OOM observations unavailable")
            totals, changes = {}, {}
        jobs = [
            replace(
                j,
                memory_bytes=sum(metrics[j.id]) if j.id in metrics else j.memory_bytes,
                oom_kill=totals.get(j.id),
                oom_kill_delta=changes.get(j.id),
            )
            for j in jobs
        ]
        host = replace(host, groups=pressure_groups)
        nodes = {j.id for j in jobs}
        messages = [m for m in messages if m.source in nodes and m.target in nodes]
        messages.sort(key=lambda m: (timestamp(m.at), m.source, int(m.id.rsplit(":", 1)[-1])))
        direct_messages.sort(
            key=lambda m: (timestamp(m.recorded_at or m.at), m.source, int(m.id.rsplit(":", 1)[-1]))
        )
        edges = {}
        for m in messages:
            key = m.source, m.target
            count = edges[key].count + 1 if key in edges else 1
            edges[key] = PeerEdge(f"{m.source}->{m.target}", m.source, m.target, count, m.at, m.kind)
        owner_rows = []
        owner_names = (
            {p.name for p in self.root.iterdir() if p.is_dir() and not p.is_symlink()}
            if self.root.is_dir()
            else set()
        )
        if caller:
            owner_names &= {caller.split("/")[0]}
        if owners:
            owner_names &= {o.split("/")[0] for o in owners}
        for owner in sorted(owner_names):
            active = [j for j in jobs if j.owner == owner and not j.retired_at]
            try:
                root_data = owner_binding.read(self.root / owner)
                root_at = root_data.get("at")
                if root_at is not None:
                    timestamp(root_at)
            except (OSError, ValueError, TypeError, AttributeError):
                root_at = None
                root_data = {}
            size = None
            if storage:
                try:
                    size = sum(tree_size(Path(j.directory)) for j in active)
                except OSError:
                    errors.append(f"{owner}: storage size unavailable")
            owner_rows.append(
                Owner(
                    owner,
                    len(active),
                    sum(j.running for j in active),
                    sum(j.unanswered_urgent for j in active),
                    size,
                    root_at,
                    root_data.get("backend") if isinstance(root_data.get("backend"), str) else None,
                    root_data.get("session_id") if isinstance(root_data.get("session_id"), str) else None,
                    active_watch(self.root / owner),
                )
            )
        eligible = [i for i in retired_items if i.kind == "job"]
        dirty = [i for i in retired_items if i.is_dirty]
        retention = Retention(
            retired,
            expired,
            len(eligible) if storage else None,
            len(dirty) if storage else None,
            sum(i.bytes for i in eligible) if storage else None,
            tuple(retired_items),
            storage,
            str(self.root.parent / "archive.jsonl"),
        )
        dependencies = tuple(
            Dependency(j.id, f"heavy:{holder.id}", "exclusive heavy admission")
            for j in jobs
            if j.state == "waiting_for_heavy"
            for request in queue.requests
            if request.job == j.id and request.state == "queued"
            for holder in queue.requests
            if holder.state == "running" and (holder.exclusive or request.exclusive)
        ) + tuple(Dependency(j.id, j.waiting.peer, "declared wait") for j in jobs
                  if j.running and j.waiting and j.waiting.peer)
        group_views, group_events, replacements = [], [], {}
        for owner in sorted({j.owner for j in jobs}):
            selected = [j for j in jobs if j.owner == owner]
            selected_ids = {j.id for j in selected}
            try:
                grouped_jobs, native, views, notices = groups.evaluate(
                    self.root / owner, selected, [e for e in all_events if e.job in selected_ids], now, errors
                )
                replacements.update((e.id, e) for e in native)
                group_views.extend(views)
                group_events.extend(notices)
                job_replacements = {j.id: j for j in grouped_jobs}
                jobs = [job_replacements.get(j.id, j) for j in jobs]
            except (OSError, ValueError, TypeError, KeyError):
                errors.append(f"{owner}: group policy observation unavailable; using each")
        recent = [replacements.get(e.id, e) for e in recent]
        wake = [replacements.get(e.id, e) for e in wake if replacements.get(e.id, e).wakes]
        wake.extend(n for n in group_events if n.wakes)
        unread = [
            e
            for e in all_events
            if e.kind == "turn_completed"
            and any(
                j.id == e.job and e.offset > max(j.acknowledged_through, j.completed_through) for j in jobs
            )
        ]
        oldest = max((max(0, int(now - timestamp(e.at))) for e in unread if e.at), default=None)
        return Snapshot(
            1,
            datetime.fromtimestamp(now, timezone.utc).isoformat(),
            tuple(jobs),
            tuple(owner_rows),
            tuple(wake),
            tuple(recent),
            queue,
            host,
            quotas(now, errors) if include_quotas else (),
            retention,
            Peers(tuple(sorted(nodes)), tuple(edges.values()), tuple(messages[-100:])),
            tuple(direct_messages[-DIRECT_MESSAGE_LIMIT:]),
            dependencies,
            tuple(errors),
            groups=tuple(group_views),
            group_events=tuple(group_events),
            unacknowledged_completions=len(unread),
            oldest_unacknowledged_completion_age_seconds=oldest,
        )


def refreshed_quota(data):
    """Adapt the quota writer's fresh observation to the same snapshot/rendering contract."""
    from .status_inputs import agy_quota

    return replace(Collector().collect(include_quotas=False), quotas=(agy_quota(data, time.time()),))


def active_watch(owner):
    import fcntl

    path = owner / "watch.lock"
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return False
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        return False
    finally:
        os.close(fd)

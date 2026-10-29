"""Watch lifecycle and acknowledgement; status owns observation and assessment."""

import fcntl
import os
import time
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from . import groups, owner_binding, root_wake, status, status_render, waiting
from .acknowledgements import INFORMATIONAL_ONLY_KINDS, displayed
from .assessment import SILENCE_SECONDS
from .core import JOBS, load_state, log


@dataclass
class WakeDelivery:
    reason: Literal["event", "timeout", "empty"] = "empty"
    identity: dict | None = None
    native: bool = False
    offsets: dict[str, int] = field(default_factory=dict)
    identities: dict[str, str] = field(default_factory=dict)
    first: bool = True
    scheduled: bool = False
    native_event_owners: set[str] = field(default_factory=set)
    notices: list[tuple[Path, str]] = field(default_factory=list)

    def reset_cycle(self):
        self.reason = "empty"
        self.scheduled = False
        self.native_event_owners.clear()
        self.notices.clear()

    def deliver(self, delivery, owners, reason):
        while True:
            visible = owner_binding.filter_owners(owners, JOBS, self.identity)
            if not visible:
                return
            visible_names = {value.split("/")[0] for value in visible}
            notices = [(owner, identifier) for owner, identifier in self.notices
                       if owner.name in visible_names]
            event_owners = self.native_event_owners & visible_names
            send = delivery is not None and bool(notices or event_owners or reason in {"timeout", "error"})
            paths = [JOBS / name for name in visible_names]

            def send_locked():
                if send:
                    delivery.deliver(visible, reason, self.scheduled)

            try:
                def send_guarded():
                    with owner_binding.guard_many(paths, self.identity):
                        send_locked()

                if notices:
                    committed = groups.deliver(notices, send_locked, self.identity, paths)
                    if not committed and send:
                        send_guarded()
                elif send:
                    send_guarded()
                return
            except owner_binding.RootMismatch:
                # A handoff landed after the snapshot. Re-scope and keep other owners active.
                continue


def job_dirs(owners):
    """<owner> globs its jobs; an <owner>/<name> argument names one job. Rescanned every tick."""
    for owner in owners:
        root = JOBS / owner
        candidates = (
            [root] if (root / "state.json").is_file() else sorted(root.iterdir()) if root.is_dir() else []
        )
        for job in candidates:
            try:
                if not load_state(job).get("retiredAt"):
                    yield job
            except (OSError, ValueError):
                continue


def shown(owner, text, path=None, offset=None, identity=None):
    try:
        with owner_binding.guard(owner, identity) as binding:
            if text:
                print(text, flush=True)
            if path is not None and offset is not None and owner_binding.may_claim(binding, identity):
                displayed(path, offset)
        return True
    except owner_binding.RootMismatch:
        return False


def observed(owner, identity, callback):
    try:
        with owner_binding.guard(owner, identity) as binding:
            if owner_binding.may_claim(binding, identity):
                callback()
        return True
    except owner_binding.RootMismatch:
        return False


def watch(owners, until_event=False, stall_min=SILENCE_SECONDS // 60, timeout=None,
          offsets=None, include_info=False):
    if os.environ.get("AGENT_BRIDGE_WORKER"):
        return follow(owners, until_event, stall_min, timeout, offsets, include_info)
    identity = owner_binding.identity()
    delivery = root_wake.prepare(owners)
    wake = WakeDelivery(identity=identity, native=delivery is not None)
    if delivery is not None:
        print("watch: native Codex root delivery ready", flush=True)
    deadline = time.monotonic() + timeout if timeout else None
    with ExitStack() as stack:
        for owner in {value.split("/")[0] for value in owners}:
            from .core import resolve_job

            resolve_job(f"{owner}/placeholder")
            folder = JOBS / owner
            folder.mkdir(mode=0o700, parents=True, exist_ok=True)
            fd = os.open(folder / "watch.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            stack.callback(os.close, fd)
            fcntl.flock(fd, fcntl.LOCK_SH)
        while True:
            try:
                completed = follow(
                    owners, until_event, stall_min, timeout,
                    offsets, include_info, wake, deadline,
                )
            except Exception as error:
                if delivery is not None:
                    try:
                        wake.deliver(delivery, owners, "error")
                    except Exception as delivery_error:
                        error.add_note(f"Native root delivery also failed ({type(delivery_error).__name__})")
                raise
            reason = wake.reason
            if reason != "empty":
                wake.deliver(delivery, owners, reason)
            if delivery is not None and until_event and reason == "event" and wake.scheduled:
                wake.reset_cycle()
                continue
            return completed


def follow(owners, until_event=False, stall_min=SILENCE_SECONDS // 60, timeout=None,
           offsets=None, include_info=False, wake=None, deadline=None):
    """Printing records display, never acknowledgement. Launch offsets cannot hide pending events."""
    if deadline is None and timeout:
        deadline = time.monotonic() + timeout
    collector = status.Collector(JOBS, warmup=True)
    if wake is None:
        offsets, identities, first = {}, {}, True
    else:
        offsets, identities, first = wake.offsets, wake.identities, wake.first
    notices, waits = {}, {}
    idle_ticks = 0
    host_printed, host_warned, oom_seen = None, False, {}
    shown_groups = set()
    while True:
        active_owners = owner_binding.filter_owners(
            owners, JOBS, wake.identity if wake is not None else None
        )
        if not active_owners:
            if wake is not None:
                wake.reason = "empty"
                wake.first = False
                wake.scheduled = False
            return True
        try:
            with owner_binding.guard_many(
                [JOBS / value.split("/")[0] for value in active_owners],
                wake.identity if wake is not None else None,
            ):
                snapshot = collector.collect(active_owners, stall_min, include_quotas=False)
        except owner_binding.RootMismatch:
            continue
        now = collector.observed_at
        host = status_render.pressure(snapshot.pressure, snapshot.heavy)
        if host_printed is None or now - host_printed >= 60:
            print(host, flush=True)
            host_printed = now
        if snapshot.pressure.warning and not host_warned:
            print(
                f"WARNING: host overloaded: {snapshot.pressure.warning}; pause heavy work | {host}",
                flush=True,
            )
            host_warned = True
        for group in snapshot.pressure.groups:
            if Path(group.id).name == "codex.slice" and group.oom_kill is not None:
                old = oom_seen.get(group.id)
                if group.oom_kill and (old is None or group.oom_kill > old):
                    change = "total recorded" if old is None else "increased"
                    print(
                        f"WARNING: codex.slice oom_kill={group.oom_kill} ({change}); pause heavy work",
                        flush=True,
                    )
                oom_seen[group.id] = group.oom_kill
        jobs = {j.id: j for j in snapshot.jobs if not j.retired_at}
        awaiting_batch = any(g.held_completions and g.policy.wake != "quiet" for g in snapshot.groups)
        awaiting_reminder = any(g.next_reminder_at is not None for g in snapshot.groups)
        if wake is not None:
            wake.scheduled = awaiting_batch or awaiting_reminder
        for job in jobs.values():
            path = Path(job.directory)
            if identities.get(job.id) != job.log_identity:
                offsets[job.id] = job.acknowledged_through
                identities[job.id] = job.log_identity
            if job.running:
                known = job.stall.state == "known"
                if first or known and waits.get(job.id) != job.state:
                    if not shown(
                        path.parent,
                        status_render.job_status(job),
                        identity=wake.identity if wake else None,
                    ):
                        continue
                    if job.state == "waiting_for_heavy":
                        if not observed(
                            path.parent, wake.identity if wake else None,
                            lambda: log(path, "heavy_wait", level="info", message=job.reason),
                        ):
                            continue
                waits[job.id] = job.state
                assessment = job.stall
                if assessment.state in {"long-command", "overdue-wait"} and assessment.notice_id:
                    try:
                        if not observed(
                            path.parent, wake.identity if wake else None,
                            lambda: waiting.notice(path, assessment),
                        ):
                            continue
                    except (OSError, ValueError):
                        pass  # the assessment remains visible if the notice ledger is unavailable
                if assessment.state in {"slow", "stalled"} and notices.get(job.id) != assessment.state:
                    if not shown(
                        path.parent,
                        status_render.notice(job),
                        identity=wake.identity if wake else None,
                    ):
                        continue
                    if assessment.state == "slow":
                        if not observed(
                            path.parent, wake.identity if wake else None,
                            lambda: log(
                                path, "slow", level="info",
                                recentSeconds=assessment.recent_step_seconds,
                                usualSeconds=assessment.usual_step_seconds,
                                message=assessment.reason,
                            ),
                        ):
                            continue
                    else:
                        if not observed(
                            path.parent, wake.identity if wake else None,
                            lambda: log(
                                path, "stalled", level="info",
                                quietSeconds=assessment.quiet_seconds,
                                busy=assessment.reason == "processes busy",
                                message=f"silent for {assessment.quiet_seconds // 60}m"
                                + (", processes busy" if assessment.reason == "processes busy" else ""),
                            ),
                        ):
                            continue
                    notices[job.id] = assessment.state
                elif assessment.state in {"known", "inactive", "ok"}:
                    notices.pop(job.id, None)
        fired = []
        group_fired = []
        for notice in snapshot.group_events:
            if not notice.seen and notice.id not in shown_groups:
                if not os.environ.get("AGENT_BRIDGE_WORKER"):
                    if wake is not None:
                        wake.notices.append((JOBS / notice.owner, notice.id))
                    elif not groups.seen(JOBS / notice.owner, notice.id):
                        continue
                shown_groups.add(notice.id)
                if not shown(JOBS / notice.owner, status_render.group_notice(notice),
                             identity=wake.identity if wake else None):
                    continue
                for event in snapshot.events:
                    if event.id in notice.completion_ids:
                        path = Path(jobs[event.job].directory)
                        shown(path.parent, "", path, event.offset, wake.identity if wake else None)
                if notice.wakes:
                    group_fired.append(notice)
        peer_messages = {m.id: m for m in snapshot.peers.recent_messages}
        for event in sorted(snapshot.events, key=lambda e: (e.job, e.offset)):
            job = jobs.get(event.job)
            if job is None or event.offset <= offsets.get(event.job, job.acknowledged_through):
                continue
            if event.id in peer_messages:
                if not shown(Path(job.directory).parent, status_render.peer_message(peer_messages[event.id]),
                             identity=wake.identity if wake else None):
                    continue
            if event.kind == "turn_completed" and event.offset <= job.completed_through:
                offsets[event.job] = event.offset
                continue
            if event.informational and event.offset > job.acknowledged_through:
                path = Path(job.directory)
                if not shown(path.parent, status_render.event(job, event), path, event.offset,
                             wake.identity if wake else None):
                    continue
                if event.wakes or include_info and event.kind not in INFORMATIONAL_ONLY_KINDS:
                    fired.append(event)
            offsets[event.job] = event.offset
        if until_event and (fired or group_fired):
            print("watch: wake events (unacknowledged until result <job> or ack <owner/job>):", flush=True)
            outstanding = {
                e.id: e
                for e in snapshot.events
                if e.job in jobs
                and (e.wakes or include_info and e.informational
                     and e.kind not in INFORMATIONAL_ONLY_KINDS)
                and e.offset > jobs[e.job].acknowledged_through
                and not (e.kind == "turn_completed" and e.offset <= jobs[e.job].completed_through)
            }
            for event in ({e.id: e for e in fired} | outstanding).values():
                path = Path(jobs[event.job].directory)
                if not shown(path.parent,
                             f"  {event.job} {event.kind} {event.at or 'time unknown'} [unacknowledged]",
                             path, event.offset, wake.identity if wake else None):
                    continue
            for notice in group_fired:
                shown(JOBS / notice.owner,
                      f"  {notice.owner} {notice.kind} {notice.at} [unacknowledged]",
                      identity=wake.identity if wake else None)
            if wake is not None:
                wake.reason = "event"
                wake.first = False
                wake.native_event_owners.update(event.job.split("/")[0] for event in fired)
            return True
        auto_reminder = until_event and wake is not None and wake.native and awaiting_reminder
        if (deadline and time.monotonic() >= deadline
                and (any(j.running for j in jobs.values()) or awaiting_batch
                     or awaiting_reminder and not auto_reminder)):
            print(f"watch: {timeout}s passed without a wake event", flush=True)
            if wake is not None:
                wake.reason = "timeout"
                wake.first = False
            return False
        if not any(j.running for j in jobs.values()) and not awaiting_batch and not awaiting_reminder:
            idle_ticks += 1
            if idle_ticks >= 5:
                print("status: no running jobs", flush=True)
                print("watch: no running jobs left, exiting")
                if wake is not None:
                    wake.first = False
                return True
        else:
            idle_ticks = 0
        first = False
        if wake is not None:
            wake.first = False
        time.sleep(2)

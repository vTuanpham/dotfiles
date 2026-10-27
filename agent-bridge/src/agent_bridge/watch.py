"""Watch lifecycle and acknowledgement; status owns observation and assessment."""

import time
from pathlib import Path

from . import status, status_render
from .acknowledgements import displayed
from .core import JOBS, load_state, log


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


def watch(owners, until_event=False, stall_min=15, timeout=None, offsets=None, include_info=False):
    """Printing records display, never acknowledgement. Launch offsets cannot hide pending events."""
    deadline = time.monotonic() + timeout if timeout else None
    collector = status.Collector(JOBS, warmup=True)
    offsets, identities, notices, waits = {}, {}, {}, {}
    first, idle_ticks = True, 0
    host_printed, host_warned, oom_seen = None, False, {}
    while True:
        snapshot = collector.collect(owners, stall_min, include_quotas=False)
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
        for job in jobs.values():
            path = Path(job.directory)
            if identities.get(job.id) != job.log_identity:
                offsets[job.id] = job.acknowledged_through
                identities[job.id] = job.log_identity
            if job.running:
                known = job.stall.state == "known"
                if first or known and waits.get(job.id) != job.state:
                    print(status_render.job_status(job), flush=True)
                    if job.state == "waiting_for_heavy":
                        log(path, "heavy_wait", level="info", message=job.reason)
                waits[job.id] = job.state
                assessment = job.stall
                if assessment.state in {"slow", "stalled"} and notices.get(job.id) != assessment.state:
                    print(status_render.notice(job), flush=True)
                    if assessment.state == "slow":
                        log(
                            path,
                            "slow",
                            level="info",
                            recentSeconds=assessment.recent_step_seconds,
                            usualSeconds=assessment.usual_step_seconds,
                            message=assessment.reason,
                        )
                    else:
                        log(
                            path,
                            "stalled",
                            level="info",
                            quietSeconds=assessment.quiet_seconds,
                            busy=assessment.reason == "processes busy",
                            message=f"silent for {assessment.quiet_seconds // 60}m"
                            + (", processes busy" if assessment.reason == "processes busy" else ""),
                        )
                    notices[job.id] = assessment.state
                elif assessment.state in {"known", "inactive", "ok"}:
                    notices.pop(job.id, None)
        fired = []
        peer_messages = {m.id: m for m in snapshot.peers.recent_messages}
        for event in sorted(snapshot.events, key=lambda e: (e.job, e.offset)):
            job = jobs.get(event.job)
            if job is None or event.offset <= offsets.get(event.job, job.acknowledged_through):
                continue
            offsets[event.job] = event.offset
            if event.id in peer_messages:
                print(status_render.peer_message(peer_messages[event.id]), flush=True)
            if event.kind == "turn_completed" and event.offset <= job.completed_through:
                continue
            if event.informational and event.offset > job.acknowledged_through:
                print(status_render.event(job, event), flush=True)
                displayed(Path(job.directory), event.offset)
                if event.wakes or include_info:
                    fired.append(event)
        if until_event and fired:
            print("watch: wake events (unacknowledged until result <job> or ack <owner/job>):", flush=True)
            outstanding = {
                e.id: e
                for e in snapshot.events
                if e.job in jobs
                and (e.wakes or include_info and e.informational)
                and e.offset > jobs[e.job].acknowledged_through
                and not (e.kind == "turn_completed" and e.offset <= jobs[e.job].completed_through)
            }
            for event in ({e.id: e for e in fired} | outstanding).values():
                print(f"  {event.job} {event.kind} {event.at or 'time unknown'} [unacknowledged]", flush=True)
                displayed(Path(jobs[event.job].directory), event.offset)
            return True
        if deadline and time.monotonic() >= deadline:
            print(f"watch: {timeout}s passed with jobs still running", flush=True)
            return False
        if not any(j.running for j in jobs.values()):
            idle_ticks += 1
            if idle_ticks >= 5:
                print("status: no running jobs", flush=True)
                print("watch: no running jobs left, exiting")
                return True
        else:
            idle_ticks = 0
        first = False
        time.sleep(2)

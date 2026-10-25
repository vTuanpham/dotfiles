import json
import time
from pathlib import Path

from .acknowledgements import cursor_for, displayed, event_lines, pending, read_owner
from .acknowledgements import urgent as is_urgent
from .core import JOBS, load_state, log


def running(state):
    pid = state.get("runnerPid")
    if not pid or not Path(f"/proc/{pid}").exists():
        return False
    try:
        return b"agent-bridge" in Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return False


def job_dirs(owners):
    """<owner> globs its jobs; an <owner>/<name> argument names one job. Rescanned every tick."""
    for owner in owners:
        root = JOBS / owner
        candidates = ([root] if (root / "state.json").is_file()
                      else sorted(root.iterdir()) if root.is_dir() else [])
        for job in candidates:
            try:
                if not load_state(job).get("retiredAt"):
                    yield job
            except (OSError, ValueError):
                continue


def line_for(job, event, title=None):
    label = f"{job.name} ({title})" if title else job.name
    text = str(event.get("text") or event.get("question") or event.get("message") or "")
    return (
        f"{label}: {event.get('kind', '')}"
        + (f" {event['status']}" if event.get("status") else "")
        + (f" error={str(event['error'])[:200]}" if event.get("error") else "")
        + (f" | {text.replace(chr(10), ' ')[:600]}" if text else "")
    )


def watch(owners, until_event=False, stall_min=15, timeout=None, offsets=None):
    """Returns False when `timeout` seconds pass first. A built-in bound, so a root whose harness allows only
    `agent-bridge ...` commands needs no `timeout` wrapper.
    Legacy launch `offsets` never hide pending events."""
    deadline = time.monotonic() + timeout if timeout else None
    # Explicit launch offsets cannot hide older unacknowledged events either.
    offsets = {j: cursor_for(j, read_owner(j.parent))["through"] for j in job_dirs(owners)}
    identities = {}
    first, idle_ticks, stalled, first_seen, last_kind = True, 0, set(), {}, {}
    while True:
        alive = urgent = False
        fired = {}
        now = time.time()
        for job in job_dirs(owners):
            f = job / "live.jsonl"
            offsets.setdefault(job, 0)
            try:
                state = json.loads((job / "state.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                state = {}
            label = f"{job.name} ({state['title']})" if state.get("title") else job.name
            if running(state):
                alive = True
                first_seen.setdefault(job, now)
                quiet = min(
                    int(now - first_seen[job]),
                    int(now - f.stat().st_mtime) if f.exists() else 0,
                )
                if first:
                    data = f.read_bytes() if f.exists() else b""
                    messages = data.count(b'"kind":"message"')
                    try:
                        last_kind[job] = json.loads(data.splitlines()[-1]).get("kind")
                    except (IndexError, json.JSONDecodeError, AttributeError):
                        last_kind[job] = None
                    status = (
                        f"status: {label} waiting for root"
                        if last_kind[job] == "root_wait"
                        else f"status: {label} running, last event {quiet // 60}m ago, {messages} messages"
                    )
                    print(status, flush=True)
                elif last_kind.get(job) == "root_wait":
                    stalled.discard(job)
                elif quiet >= stall_min * 60 and job not in stalled:  # once per silence
                    stalled.add(job)
                    print(f"{label}: silent for {quiet // 60}m while running (stalled?)", flush=True)
                    log(job, "stalled", level="urgent", quietSeconds=quiet,
                        message=f"silent for {quiet // 60}m")
                elif quiet <= stall_min * 60:
                    stalled.discard(job)
            else:
                first_seen.pop(job, None)
                stalled.discard(job)
            if not f.exists():
                continue
            size = f.stat().st_size
            cursor = cursor_for(job, read_owner(job.parent))
            if size < offsets[job] or identities.get(job) != cursor["log"]:
                offsets[job] = cursor["through"]
            identities[job] = cursor["log"]
            for end, event in event_lines(job, offsets[job]):
                offsets[job] = end
                if event.get("kind") == "root_wait" and last_kind.get(job) != "root_wait":
                    print(f"status: {label} waiting for root", flush=True)
                last_kind[job] = event.get("kind")
                if (is_urgent(event) and end > cursor["through"]
                        and not (event.get("kind") == "turn_completed" and end <= cursor["completed"])):
                    print(line_for(job, event, state.get("title")), flush=True)
                    displayed(job, end)
                    fired[job, end] = event
                    urgent = True
        if until_event and urgent:
            outstanding = {(job, end): event for job in job_dirs(owners) for end, event in pending(job)}
            print("watch: urgent events (unacknowledged until result <job> or ack <owner/job>):", flush=True)
            for (job, end), event in (fired | outstanding).items():
                status = "unacknowledged" if (job, end) in outstanding else "acknowledged"
                print(f"  {job.parent.name}/{job.name} {event.get('kind')} "
                      f"{event.get('at') or 'time unknown'} [{status}]", flush=True)
                if status == "unacknowledged":
                    displayed(job, end)
            return True
        if deadline and time.monotonic() >= deadline:
            print(f"watch: {timeout}s passed with jobs still running", flush=True)
            return False
        if not alive:
            idle_ticks += 1
            if idle_ticks >= 5:
                if idle_ticks == 5:
                    print("status: no running jobs", flush=True)
                print("watch: no running jobs left, exiting")
                return True
        else:
            idle_ticks = 0
        first = False
        time.sleep(2)

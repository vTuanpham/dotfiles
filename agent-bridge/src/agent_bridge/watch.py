import json
import time
from collections.abc import Mapping
from pathlib import Path

from .core import JOBS


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
        if (root / "state.json").is_file():
            yield root
        elif root.is_dir():
            yield from (p for p in sorted(root.iterdir()) if (p / "state.json").is_file())


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
    `agent-bridge ...` commands needs no `timeout` wrapper. `offsets` maps job dirs to read start."""
    deadline = time.monotonic() + timeout if timeout else None
    # Files present at start are read from their end; jobs that appear later from their beginning.
    offsets = (
        dict(offsets)
        if offsets is not None
        else {
            j: (j / "live.jsonl").stat().st_size if (j / "live.jsonl").exists() else 0
            for j in job_dirs(owners)
        }
    )
    first, idle_ticks, stalled, first_seen, last_kind = True, 0, set(), {}, {}
    while True:
        alive = urgent = False
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
                elif quiet > stall_min * 60 and job not in stalled:  # once per silence
                    stalled.add(job)
                    print(f"{label}: silent for {quiet // 60}m while running (stalled?)", flush=True)
                elif quiet <= stall_min * 60:
                    stalled.discard(job)
            else:
                first_seen.pop(job, None)
                stalled.discard(job)
            if not f.exists():
                continue
            size = f.stat().st_size
            if size < offsets[job]:
                offsets[job] = 0
            with f.open("rb") as stream:  # byte offsets: live.jsonl holds UTF-8 text
                stream.seek(offsets[job])
                data = stream.read()
            complete = data[: data.rfind(b"\n") + 1]
            offsets[job] += len(complete)
            for raw in complete.splitlines():
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, Mapping):
                    continue
                if event.get("kind") == "root_wait" and last_kind.get(job) != "root_wait":
                    print(f"status: {label} waiting for root", flush=True)
                last_kind[job] = event.get("kind")
                if event.get("level") == "urgent":
                    print(line_for(job, event, state.get("title")), flush=True)
                    urgent = True
        if until_event and urgent:
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

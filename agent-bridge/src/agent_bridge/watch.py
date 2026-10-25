import json
import math
import os
import re
import statistics
import subprocess
import time
from datetime import datetime
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


TICKS = os.sysconf("SC_CLK_TCK")
BUSY_WINDOW = 60  # seconds per activity sample
BUSY_CPU = 3.0  # CPU seconds per window (5% of a core): real work, well above an idle app-server
BUSY_BYTES = 16 * 1024  # TCP bytes per window: a live model stream or download, well above keep-alives
BUSY_STALL_FACTOR = 3  # a busy silent job is reported after 3x --stall-min
PACE_RECENT, PACE_BASELINE = 5, 10  # model steps judged, and earlier steps they are judged against
PACE_SLOW, PACE_FLOOR = 5, 60  # slow: recent steps 5x the job's usual, and at least a minute each
SS_PID = re.compile(r"pid=(\d+)")
SS_BYTES = re.compile(r"\bbytes_(?:acked|received):(\d+)")


def tree_cpu(pid):
    """CPU seconds used so far by `pid` and its live descendants, with their pids; None if unreadable."""
    if not pid or not Path(f"/proc/{pid}/stat").exists():
        return None
    total, stack, pids = 0, [pid], set()
    while stack:
        pid = stack.pop()
        try:
            # utime and stime: the 12th and 13th fields after the parenthesised command name
            fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
            total += int(fields[11]) + int(fields[12])
            pids.add(pid)
            for task in Path(f"/proc/{pid}/task").iterdir():
                stack.extend(int(child) for child in (task / "children").read_text().split())
        except (OSError, IndexError, ValueError):
            continue  # a process that exited mid-walk
    return total / TICKS, pids


def socket_bytes(pids):
    """TCP bytes moved so far per socket owned by `pids`, from `ss` (per-process I/O counters are not
    always compiled in, and /proc/net counts a whole namespace). {} when `ss` is unavailable."""
    try:
        out = subprocess.run(["ss", "-tinpH"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    sockets, owner = {}, None
    for line in out.splitlines():
        if not line[:1].isspace():  # a socket row: state, queues, local and peer address, users
            row = line.split()
            owner = " ".join(row[3:5]) if pids & {int(p) for p in SS_PID.findall(line)} else None
        elif owner:  # its tcp_info line
            sockets[owner] = sum(int(n) for n in SS_BYTES.findall(line))
    return sockets


def pace(path):
    """(recent, usual, unreported) for the seconds between a command's end and the next one's start: how
    long each model step takes. Recent is the median of the last PACE_RECENT steps, usual of every step
    before them, unreported the steps since the log's last `slow` event. None while there are fewer
    than PACE_RECENT + PACE_BASELINE steps, or for a backend that logs no commands."""
    gaps, last, reported = [], None, None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        try:
            event = json.loads(line)
            at = datetime.fromisoformat(event["at"]).timestamp()
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue
        kind = event.get("kind")
        if kind in ("turn_started", "command_end"):
            last = at
        elif kind == "command_start" and last is not None:
            gaps.append(at - last)
            last = None
        elif kind == "slow":
            reported = len(gaps)
    if len(gaps) < PACE_RECENT + PACE_BASELINE:
        return None
    unreported = len(gaps) - (reported if reported is not None else -PACE_RECENT)
    return statistics.median(gaps[-PACE_RECENT:]), statistics.median(gaps[:-PACE_RECENT]), unreported


def busy(before, after):
    """Whether a job's processes did real work between two (time, cpu, sockets) samples."""
    scale = (after[0] - before[0]) / BUSY_WINDOW
    moved = sum(max(0, n - before[2].get(key, 0)) for key, n in after[2].items())
    return after[1] - before[1] >= BUSY_CPU * scale or moved >= BUSY_BYTES * scale


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
    samples, busy_at = {}, {}  # job -> (time, CPU seconds) at the last sample; job -> last time it was busy
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
                # a long command or download logs nothing; CPU or TCP traffic of the job's processes is work
                if job not in samples or now - samples[job][0] >= BUSY_WINDOW:
                    tree = tree_cpu(state.get("runnerPid"))
                    if tree is not None:
                        sample = (now, tree[0], socket_bytes(tree[1]))
                        if job in samples and busy(samples[job], sample):
                            busy_at[job] = now
                        samples[job] = sample
                    steps = pace(f)
                    # once per window of fresh steps, across watches: the log holds the last report
                    slower = steps and steps[0] >= max(PACE_FLOOR, PACE_SLOW * steps[1])
                    if slower and steps[2] >= PACE_RECENT:
                        recent, usual = round(steps[0]), round(steps[1])
                        print(f"{label}: slow, model steps take {recent}s (usually {usual}s)", flush=True)
                        log(job, "slow", level="urgent", recentSeconds=recent, usualSeconds=usual,
                            message=f"model steps take {recent}s, usually {usual}s")
                quiet = min(
                    int(now - first_seen[job]),
                    int(now - f.stat().st_mtime) if f.exists() else 0,
                )
                # busy work earns a longer silence, not an endless one: a native call can spin forever
                working = now - busy_at.get(job, -math.inf) <= 2 * BUSY_WINDOW
                limit = stall_min * 60 * (BUSY_STALL_FACTOR if working else 1)
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
                elif quiet >= limit and job not in stalled:  # once per silence
                    stalled.add(job)
                    why = "processes busy: a long command, or a spinning one?" if working else "stalled?"
                    print(f"{label}: silent for {quiet // 60}m while running ({why})", flush=True)
                    log(job, "stalled", level="urgent", quietSeconds=quiet, busy=working,
                        message=f"silent for {quiet // 60}m" + (", processes busy" if working else ""))
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

"""Process activity and model-step timing observations used by the status owner."""

import os
import re
import statistics
import subprocess
from pathlib import Path

from .core import command_env
from .status_inputs import timestamp


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
        out = subprocess.run(
            ["ss", "-tinpH"], env=command_env(), capture_output=True, text=True, timeout=5
        ).stdout
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


def pace(events):
    """(recent, usual, unreported) for the seconds between a command's end and the next one's start: how
    long each model step takes. Recent is the median of the last PACE_RECENT steps, usual of every step
    before them, unreported the steps since the log's last `slow` event. None while there are fewer
    than PACE_RECENT + PACE_BASELINE steps, or for a backend that logs no commands."""
    gaps, last, reported = [], None, None
    for event in events:
        try:
            at = timestamp(event["at"])
        except (KeyError, TypeError, ValueError):
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

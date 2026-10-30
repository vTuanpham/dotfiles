"""Root-only inspection, pause and cancellation of cooperative heavy requests."""

import os
import signal
import sys
import time

from . import heavy
from .identity import identity

TERM_GRACE = 5


def request_id(path):
    return path.stem.rsplit("-", 1)[-1][:12]


def require_root():
    if os.environ.get("AGENT_RESOURCES_WORKER"):
        raise RuntimeError("delegated workers cannot control the heavy queue; ask the root")


def listing():
    require_root()
    folder = heavy.prepare()
    with heavy.gate(folder):
        paused = heavy.pause_state(folder)
        if paused["reason"] is not None:
            print(f"paused by root: {paused['reason']}")
        now = time.monotonic_ns()
        for path, row in heavy.entries(folder):
            state = "running" if row["running"] else "queued"
            if row["control"]["cancelled"]:
                state = "cancelling"
            elapsed = (now - row["started_ns"] if row["running"] else heavy.waited_ns(row, paused, now))
            label = "elapsed" if row["running"] else "wait"
            print(f"{request_id(path)} {row['job'] or '-'} {row['command']} "
                  f"{row['need'] / heavy.MIB:g}MiB {'yes' if row['exclusive'] else 'no'} "
                  f"{state} {label}={max(0, elapsed) // 10**9}s yes(kernel-lock)")


def pause(reason):
    require_root()
    if not reason or len(reason) > 200 or any(ord(c) < 32 or ord(c) == 127 for c in reason):
        raise ValueError("pause reason must be 1–200 characters without control characters")
    folder = heavy.prepare()
    with heavy.gate(folder):
        heavy.entries(folder)
        state = heavy.pause_state(folder)
        if state["since_ns"] is None:
            state["since_ns"] = time.monotonic_ns()
        state["reason"] = reason
        heavy.write_state(folder / "pause.json", state)
    print(f"heavy: paused by root: {reason}; running commands continue")


def resume():
    require_root()
    folder = heavy.prepare()
    with heavy.gate(folder):
        state = heavy.pause_state(folder)
        state["total_ns"] = heavy.pause_clock(state, time.monotonic_ns())
        state.update(reason=None, since_ns=None)
        heavy.write_state(folder / "pause.json", state)
    print("heavy: admissions resumed")


def process_has_request(pid, path):
    """Check the actual inherited descriptor, not a possibly reused recorded PID."""
    expected = path.stat()
    for descriptor in (heavy.PROC / str(pid) / "fd").glob("*"):
        try:
            actual = descriptor.stat()
            if (actual.st_dev, actual.st_ino) == (expected.st_dev, expected.st_ino):
                return True
        except OSError:
            continue
    return False


def group_members(pgid, only_pid=None):
    members = {}
    processes = [heavy.PROC / str(only_pid)] if only_pid is not None else heavy.PROC.glob("[0-9]*")
    for process in processes:
        try:
            fields = (process / "stat").read_text().rpartition(")")[2].split()
            if (pgid is None or int(fields[2]) == pgid) and fields[0] != "Z":
                members[int(process.name)] = fields[19]  # starttime distinguishes recycled PIDs
        except (OSError, ValueError, IndexError):
            continue
    return members


def cancel(target):
    require_root()
    folder = heavy.prepare()
    with heavy.gate(folder):
        matches = [(path, row) for path, row in heavy.entries(folder)
                   if target in (request_id(path), path.stem, row.get("job"))]
        if len(matches) != 1:
            raise ValueError("ambiguous heavy request; use an id from heavy list" if matches
                             else "no live heavy request matches; use heavy list")
        selected, request = matches[0]
    if request["owner"] is not None and request["owner"] != identity():
        raise RuntimeError("request belongs to a different root session")
    _cancel_request(folder, target, selected)


def _cancel_request(folder, target, selected):
    with heavy.gate(folder):
        matches = [(path, row) for path, row in heavy.entries(folder)
                   if path == selected and target in (request_id(path), path.stem, row.get("job"))]
        if len(matches) != 1:
            raise RuntimeError("heavy request changed before cancellation; refresh heavy list")
        path, row = matches[0]
        if row["owner"] is not None and row["owner"] != identity():
            raise RuntimeError("request belongs to a different root session")
        control = row["control"]
        if not row["running"]:
            control["cancelled"] = True
            heavy.write_state(heavy.control_path(path), control)
            print(f"heavy: cancelled queued request {request_id(path)}; waiter exits {heavy.CANCELLED_EXIT}")
            return
        namespace = os.readlink(heavy.PROC / "self/ns/pid")
        pid = row.get("pid") if row.get("namespace") == namespace else heavy.resolve_host_pid(row)
        if pid is None:
            raise RuntimeError("holder PID is not visible here; run cancellation from the host root harness")
        # Verify the inherited descriptor; never signal the worker's process group.
        if not process_has_request(pid, path):
            raise RuntimeError("holder identity changed; no signal sent; refresh heavy list")
        grouped = control["group"] and os.getpgid(pid) == pid
        members = group_members(pid) if grouped else group_members(None, only_pid=pid)
        if not members:
            raise RuntimeError("holder exited during cancellation; refresh heavy list")
        control["cancelled"] = True
        heavy.write_state(heavy.control_path(path), control)
        send = os.killpg if grouped else os.kill
        try:
            send(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    print(f"heavy: stopping running request {request_id(path)} (SIGTERM; {TERM_GRACE}s grace)",
          file=sys.stderr, flush=True)
    deadline = time.monotonic() + TERM_GRACE
    while True:
        current = group_members(pid) if grouped else group_members(None, only_pid=pid)
        if not any(current.get(p) == birth for p, birth in members.items()):
            break  # the original process/group is gone; never signal a recycled id
        members.update(current)
        if time.monotonic() >= deadline:
            try:
                send(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            break
        time.sleep(0.1)
    deadline = time.monotonic() + 2
    while True:
        with heavy.gate(folder):
            remaining = any(p == path for p, _ in heavy.entries(folder))
        if not remaining:
            break
        if time.monotonic() >= deadline:
            raise RuntimeError("stop signals sent but request still holds its lock; inspect heavy list")
        time.sleep(0.05)
    print(f"heavy: cancelled running request {request_id(path)}")

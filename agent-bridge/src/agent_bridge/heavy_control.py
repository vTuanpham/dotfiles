"""Root-only inspection, pause and cancellation of cooperative heavy requests."""

import argparse
import os
import signal
import sys
import time

from . import heavy
from .core import WORKER_FLAG

TERM_GRACE = 5


def request_id(path):
    return path.stem.rsplit("-", 1)[-1][:12]


def require_root():
    if os.environ.get(WORKER_FLAG):
        raise RuntimeError("delegated workers cannot control the heavy queue; ask the root")


def listing():
    require_root()
    from .status import Collector
    from .status_render import heavy_list

    snapshot = Collector().collect(include_quotas=False)
    if snapshot.heavy.error:
        raise ValueError(snapshot.heavy.error)
    print("\n".join(heavy_list(snapshot)))


def pause(reason):
    require_root()
    if not reason or len(reason) > 200 or any(ord(c) < 32 or ord(c) == 127 for c in reason):
        raise ValueError("pause reason must be 1–200 characters without control characters")
    folder = heavy.prepare()
    with heavy.gate(folder):
        if any(not row["running"] and row["control"] is None for _, row in heavy.entries(folder)):
            raise RuntimeError("legacy waiters cannot observe pause; let them drain before pausing")
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
        path, row = matches[0]
        control = row["control"]
        if not row["running"]:
            if control is None:
                raise RuntimeError("legacy waiter predates queue control; let it finish or stop its job")
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
        grouped = control is not None and control["group"] and os.getpgid(pid) == pid
        members = group_members(pid) if grouped else group_members(None, only_pid=pid)
        if not members:
            raise RuntimeError("holder exited during cancellation; refresh heavy list")
        if control is not None:
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


def main(argv):
    require_root()
    parser = argparse.ArgumentParser(prog="agent-bridge heavy")
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("list", help="list live heavy requests with ids")
    commands.add_parser("cancel", help="cancel one request by id or unambiguous owner/job").add_argument(
        "target")
    commands.add_parser("pause", help="pause new admissions; running work continues").add_argument(
        "--reason", default="maintenance", help="reason printed to waiters (up to 200 characters)")
    commands.add_parser("resume", help="resume heavy admissions")
    args = parser.parse_args(argv)
    if args.action == "list":
        listing()
    elif args.action == "cancel":
        cancel(args.target)
    elif args.action == "pause":
        pause(args.reason)
    else:
        resume()

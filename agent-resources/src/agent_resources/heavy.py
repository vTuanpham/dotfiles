"""Cooperative host admission, shared by all bridge owners and harnesses of one UID."""

import fcntl
import json
import os
import shutil
import stat
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .identity import identity
from .resources import MIB, limits, memory_size, pressure, wait_reason

PROC = Path("/proc")
DEFAULT_NEED = 1024 * MIB
BACKFILL_SECONDS = 300
CANCELLED_EXIT = 125


def directory():
    # A host queue must not change with a harness's isolated HOME or TMPDIR.
    path = Path(os.environ.get("AGENT_RESOURCES_HOME", f"/tmp/agent-resources-{os.getuid()}"))
    if not path.is_absolute():
        raise ValueError("AGENT_RESOURCES_HOME must be absolute")
    return path


def prepare():
    path = directory()
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RuntimeError("heavy directory must be an owned, private directory, not a symlink")
    return path


def locked_file(path):
    return os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)


def write_request(fd, row):
    os.lseek(fd, 0, os.SEEK_SET)
    os.ftruncate(fd, 0)
    os.write(fd, json.dumps(row).encode())


def reservation_path(path):
    return path.with_suffix(".request.need")


def control_path(path):
    return path.with_suffix(".request.control")


def read_state(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None
    try:
        if os.fstat(fd).st_size > 4096:
            raise ValueError("oversized heavy control state")
        data = json.loads(os.read(fd, 4096))
        if data is None:
            raise ValueError("invalid heavy control state")
        return data
    finally:
        os.close(fd)


def write_state(path, data):
    temporary = path.parent / f".state-{uuid.uuid4().hex}"
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    try:
        write_request(fd, data)
        os.replace(temporary, path)
    finally:
        os.close(fd)
        temporary.unlink(missing_ok=True)


def control(path):
    data = read_state(control_path(path))
    if (
            type(data) is not dict or set(data) != {"group", "cancelled", "pause_ns"}
            or type(data["group"]) is not bool or type(data["cancelled"]) is not bool
            or type(data["pause_ns"]) is not int or data["pause_ns"] < 0):
        raise ValueError("invalid heavy request control state")
    return data


def pause_state(folder):
    data = read_state(folder / "pause.json")
    if data is None:
        return {"reason": None, "since_ns": None, "total_ns": 0}
    if (type(data) is not dict or set(data) != {"reason", "since_ns", "total_ns"}
            or type(data["total_ns"]) is not int or data["total_ns"] < 0
            or (data["reason"] is None) != (data["since_ns"] is None)
            or data["reason"] is not None and (
                type(data["reason"]) is not str or len(data["reason"]) > 200
                or not data["reason"] or any(ord(c) < 32 or ord(c) == 127 for c in data["reason"])
                or type(data["since_ns"]) is not int or data["since_ns"] < 0)):
        raise ValueError("invalid heavy pause state")
    return data


def pause_clock(paused, now_ns):
    return paused["total_ns"] + (max(0, now_ns - paused["since_ns"])
                                 if paused["since_ns"] is not None else 0)


def waited_ns(row, paused, now_ns):
    elapsed = max(0, now_ns - row["queued_ns"])
    if row.get("control") is not None:
        elapsed -= max(0, pause_clock(paused, now_ns) - row["control"]["pause_ns"])
    return max(0, elapsed)


def reservation(path, row):
    try:
        fd = os.open(reservation_path(path), os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        raise ValueError("missing heavy reservation") from None
    try:
        if os.fstat(fd).st_size > 4096:
            raise ValueError("oversized heavy reservation")
        data = json.loads(os.read(fd, 4096))
    finally:
        os.close(fd)
    if (type(data) is not dict or set(data) != {"need", "exclusive", "queued_ns", "cap"}
            or type(data["need"]) is not int or data["need"] < 1
            or type(data["exclusive"]) is not bool
            or type(data["queued_ns"]) is not int or data["queued_ns"] < 0
            or data["cap"] is not None and (type(data["cap"]) is not int or data["cap"] < 1)):
        raise ValueError("invalid heavy reservation")
    return data


def choose(rows, budget, slots, now_ns, free=None):
    """FIFO among fitting requests; five-minute heads and exclusive requests fence backfill.

    `budget` bounds the declared needs of all holders (capacity, not live use); `free` is live
    headroom, which already reflects what running holders use, so they are not counted twice.
    """
    running = [row for _, row in rows if row["running"]]
    waiting = [(path, row) for path, row in rows if not row["running"]]
    reserved = sum(row["need"] for row in running)

    def fits(need):
        return reserved + need <= budget and (free is None or need <= free)

    caps = [row["cap"] for _, row in rows if row["cap"] is not None]
    if slots is not None:
        caps.append(slots)
    cap = min(caps) if caps else None
    if any(row["exclusive"] for row in running):
        return None, reserved, cap, "exclusive holder is running"
    if cap is not None and len(running) >= cap:
        return None, reserved, cap, "hard job cap reached"
    if not waiting:
        return None, reserved, cap, ""
    head_path, head = waiting[0]
    if head["exclusive"]:
        if running:
            return None, reserved, cap, "earlier exclusive request is waiting for all holders"
        return (head_path if fits(head["need"]) else None), reserved, cap, "exclusive request"
    if fits(head["need"]):
        return head_path, reserved, cap, "FIFO"
    if now_ns - head["queued_ns"] >= BACKFILL_SECONDS * 1000000000:
        return None, reserved, cap, "backfill paused: head has waited 5m"
    for path, row in waiting[1:]:
        if row["exclusive"]:
            break
        if fits(row["need"]):
            return path, reserved, cap, "backfill: head does not fit"
    return None, reserved, cap, "declared memory needs do not fit"


def resolve_host_pid(row):
    """The host runner can annotate a namespace-local PID; workers need no cross-namespace access."""
    if not row.get("host_namespace") or os.readlink(PROC / "self/ns/pid") != row["host_namespace"]:
        return None
    for process in PROC.glob("[0-9]*"):
        try:
            if os.readlink(process / "ns/pid") != row["namespace"]:
                continue
            for line in (process / "status").read_text().splitlines():
                if line.startswith("NSpid:") and int(line.split()[-1]) == row["pid"]:
                    return int(process.name)
        except (OSError, ValueError):
            continue
    return None


@contextmanager
def gate(folder):
    fd = locked_file(folder / "gate.lock")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def entries(folder, own=None, dead=None):
    """Under gate: dead requests have no kernel lock, even after SIGKILL or PID reuse."""
    result = []
    for temporary in folder.glob(".state-*"):
        temporary.unlink()
    for suffix in ("need", "control"):
        for metadata in folder.glob(f"*.request.{suffix}"):
            if not metadata.with_suffix("").exists():
                metadata.unlink()
    for path in sorted(folder.glob("*.request")):
        fd = locked_file(path)
        try:
            if path != own:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    pass
                else:
                    if dead is not None:
                        try:
                            stale = json.loads(os.read(fd, 4096))
                            if isinstance(stale, dict) and stale.get("running") is True:
                                dead.append(stale.get("job") or "standalone")
                        except (ValueError, UnicodeDecodeError):
                            pass
                    path.unlink()
                    reservation_path(path).unlink(missing_ok=True)
                    control_path(path).unlink(missing_ok=True)
                    continue
            if os.fstat(fd).st_size > 4096:
                raise ValueError("oversized heavy queue entry")
            row = json.loads(os.read(fd, 4096))
            required = {"running", "slots"}
            metadata = {"job", "owner", "command", "pid", "namespace", "host_namespace", "host_pid",
                        "started_at", "started_ns"}
            if (type(row) is not dict or set(row) != required | metadata
                    or type(row["running"]) is not bool or type(row["slots"]) is not int
                    or row["slots"] < 1):
                raise ValueError("invalid heavy queue entry")
            if row["owner"] is not None and (type(row["owner"]) is not str or len(row["owner"]) > 400):
                raise ValueError("invalid heavy owner")
            if set(row) == required | metadata:
                if (any(type(row[key]) is not str for key in ("job", "command", "namespace"))
                        or type(row["pid"]) is not int or row["pid"] < 1
                        or row["host_namespace"] is not None and type(row["host_namespace"]) is not str
                        or row["host_pid"] is not None
                        and (type(row["host_pid"]) is not int or row["host_pid"] < 1)
                        or row["running"] and (type(row["started_at"]) is not str
                                               or type(row["started_ns"]) is not int
                                               or row["started_ns"] < 0)):
                    raise ValueError("invalid heavy holder metadata")
                if row["host_pid"] is None:
                    row["host_pid"] = resolve_host_pid(row)
                    if row["host_pid"] is not None:
                        write_request(fd, row)
            row.update(reservation(path, row))
            row["control"] = control(path)
            result.append((path, row))
        finally:
            os.close(fd)
    return result




def scope_prefix(memory_max):
    """Probe only a no-op. Never retry a user's command after an ambiguous scope failure."""
    if not memory_max:
        return []
    if not memory_max.isdecimal() or int(memory_max) < 1:
        raise ValueError("--memory-max-mib must be a positive integer")
    prefix = ["systemd-run", "--user", "--scope", "--quiet", "--no-ask-password",
              "--slice-inherit", "-p", f"MemoryMax={int(memory_max) * MIB}"]
    try:
        if shutil.which("systemd-run"):
            help_text = subprocess.run(["systemd-run", "--help"], capture_output=True,
                                       text=True, timeout=5).stdout
            # Before this option existed, scope mode passed argv directly to execve.
            if "--expand-environment=" in help_text:
                prefix.insert(1, "--expand-environment=no")
            if subprocess.run([*prefix, "--", "/usr/bin/true"],
                              capture_output=True, timeout=5).returncode == 0:
                return prefix
    except (OSError, subprocess.SubprocessError):
        pass
    raise RuntimeError("systemd user scope unavailable; requested memory cap cannot be applied")


def run(command, memory_max=None, mem=None, exclusive=False):
    if not command:
        raise ValueError("heavy needs a command after --")
    if os.environ.get("AGENT_RESOURCES_ACTIVE"):
        raise RuntimeError("nested heavy commands would deadlock; wrap the outer command only")
    need = memory_size(mem) if mem is not None else DEFAULT_NEED
    host = pressure()
    # Moving a worker into a sibling scope would discard its inherited per-job caps.
    inherited = host.slice is not None or any(g.maximum is not None for g in host.groups)
    if memory_max and inherited:
        if not memory_max.isdecimal() or int(memory_max) < 1:
            raise ValueError("--memory-max-mib must be a positive integer")
        if host.capacity > int(memory_max) * MIB:
            raise RuntimeError("cannot tighten the inherited memory cap in this command")
        else:
            print("heavy: inherited cgroup already enforces the requested cap or tighter", file=sys.stderr)
    # Standalone commands may enter a scope before acquiring any lock descriptors.
    prefix = scope_prefix(memory_max) if not inherited else []
    if prefix:
        inner = [sys.executable, "-m", "agent_resources.cli", "run"]
        if mem is not None:
            inner += ["--mem", str(need)]
        if exclusive:
            inner += ["--exclusive"]
        inner += ["--", *command]
        os.execvpe(prefix[0], [*prefix, "--", *inner], dict(os.environ))
    policy = limits(host)
    if need + policy.available > host.shared_capacity:
        raise ValueError("declared memory need exceeds shared capacity after the safety floor")
    folder = prepare()
    path = folder / f"{time.time_ns():020d}-{uuid.uuid4().hex}.request"
    fd = None
    try:
        with gate(folder):
            entries(folder)
            fd = locked_file(path)
            fcntl.flock(fd, fcntl.LOCK_EX)
            namespace = os.readlink(PROC / "self/ns/pid")
            host_namespace = os.environ.get("AGENT_RESOURCES_HOST_PID_NAMESPACE")
            if not host_namespace and not os.environ.get("AGENT_RESOURCES_WORKER"):
                host_namespace = namespace
            request = {"running": False, "slots": policy.slots or 1,
                       "job": os.environ.get("AGENT_RESOURCES_JOB", ""), "owner": identity(),
                       "command": Path(command[0]).name, "pid": os.getpid(), "namespace": namespace,
                       "host_namespace": host_namespace,
                       "host_pid": os.getpid() if namespace == host_namespace else None,
                       "started_at": None, "started_ns": None}
            write_request(fd, request)
            metadata_fd = os.open(reservation_path(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL
                                  | os.O_NOFOLLOW, 0o600)
            try:
                write_request(metadata_fd, {"need": need, "exclusive": exclusive,
                                            "queued_ns": time.monotonic_ns(), "cap": policy.slots})
            finally:
                os.close(metadata_fd)
            write_state(control_path(path), {"group": False, "cancelled": False,
                        "pause_ns": pause_clock(pause_state(folder), time.monotonic_ns())})
        last, reported = None, 0
        if host.groups:
            time.sleep(1)  # first CPU sample needs an interval, not a lifetime-average guess
        while True:
            host = pressure(host)
            with gate(folder):
                dead = []
                rows = entries(folder, path, dead)
                own = dict(rows)[path]
                if own["control"]["cancelled"]:
                    print(f"heavy: cancelled by root while queued; exit={CANCELLED_EXIT}",
                          file=sys.stderr, flush=True)
                    raise SystemExit(CANCELLED_EXIT)
                rows = [(p, row) for p, row in rows
                        if row["running"] or not (row.get("control") or {}).get("cancelled")]
                paused = pause_state(folder)
                waiting = [p for p, row in rows if not row["running"]]
                position = waiting.index(path) + 1
                active = sum(row["running"] for _, row in rows)
                reason = wait_reason(host, policy, shared=True)
                budget = max(0, host.shared_capacity - policy.available)
                free = max(0, host.shared_headroom - policy.available)
                selected, reserved, cap, queue_reason = choose(
                    rows, budget, policy.slots, time.monotonic_ns(), free)
                if paused["reason"] is not None:
                    queue_reason = f"paused by root: {paused['reason']}"
                    selected = None
                if selected == path and not reason:
                    # Isolate only this admitted command and its children, never its worker runner.
                    if os.getpgrp() != os.getpid():
                        os.setpgid(0, 0)
                    own["control"]["group"] = True
                    write_state(control_path(path), own["control"])
                    request.update(running=True, started_at=datetime.now(timezone.utc).isoformat(),
                                   started_ns=time.monotonic_ns())
                    write_request(fd, request)
                    break
            occupied = f"{active}/{cap} slots busy" if cap is not None else f"{active} running; hard cap=none"
            message = (f"queue position {position}/{len(waiting)}; {occupied}; need={need / MIB:g}MiB "
                       f"reserved={reserved / MIB:g}MiB budget={budget / MIB:g}MiB "
                       f"free={free / MIB:g}MiB; {queue_reason}")
            if selected is not None and selected != path and not reason:
                ahead = dict(rows)[selected].get("job") or "standalone"
                message += f"; free slot is going to the earlier request ({ahead})"
            if reason:
                message += f"; {reason}"
            for _, holder in rows:
                if holder["running"]:
                    elapsed = (max(0, (time.monotonic_ns() - holder["started_ns"]) // 1000000000)
                               if holder.get("started_ns") is not None else 0)
                    message += (f"; holder={holder.get('job') or 'standalone'} "
                                f"command={holder.get('command') or 'unknown'} elapsed={elapsed}s "
                                f"need={holder['need'] / MIB:g}MiB "
                                f"exclusive={'yes' if holder['exclusive'] else 'no'} "
                                f"alive=yes (kernel lock) host_pid={holder.get('host_pid') or 'unavailable'}")
            now = time.monotonic()
            if dead:
                print("heavy: holder alive=no; cleared dead holder record", file=sys.stderr, flush=True)
            if paused["reason"] is None and waited_ns(own, paused, time.monotonic_ns()) >= 1800 * 10**9:
                message += "; wait exceeds 30 minutes; report this to the coordinator"
            state = (position, len(waiting), active, reason, queue_reason,
                     tuple(p.name for p, row in rows if row["running"]))
            if (state != last and now - reported >= 5) or last is None or now - reported >= 30:
                print(f"heavy: waiting, {message}; normal queue wait: do not report unless the holder "
                      "is dead or the wait exceeds 30m excluding root pauses", file=sys.stderr, flush=True)
                last, reported = state, now
            time.sleep(1)
        print(f"heavy: admitted; need={need / MIB:g}MiB exclusive={'yes' if exclusive else 'no'} "
              f"headroom={host.shared_headroom / MIB:.0f}MiB load1={host.load:.2f}",
              file=sys.stderr, flush=True)
        os.set_inheritable(fd, True)
        # Replace the wrapper: signals, stdio and exit status belong directly to the command.
        os.execvpe(command[0], command, {**os.environ, "AGENT_RESOURCES_ACTIVE": "1"})
    finally:
        if fd is not None:
            os.close(fd)
        with gate(folder):
            path.unlink(missing_ok=True)
            reservation_path(path).unlink(missing_ok=True)
            control_path(path).unlink(missing_ok=True)

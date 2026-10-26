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
from dataclasses import dataclass
from pathlib import Path

from .core import command_env, stamp
from .resources import MIB, Pressure, limits, pressure, wait_reason

PROC = Path("/proc")


def directory():
    # Fixed across HOME/AGENT_BRIDGE_HOME and harness-specific temporary directories.
    path = Path(os.environ.get("AGENT_BRIDGE_HEAVY_DIR", f"/tmp/agent-bridge-heavy-{os.getuid()}"))
    if not path.is_absolute():
        raise ValueError("AGENT_BRIDGE_HEAVY_DIR must be absolute")
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
                    continue
            if os.fstat(fd).st_size > 4096:
                raise ValueError("oversized heavy queue entry")
            row = json.loads(os.read(fd, 4096))
            old = {"running", "slots"}
            metadata = {"job", "command", "pid", "namespace", "host_namespace", "host_pid",
                        "started_at", "started_ns"}
            if (type(row) is not dict or set(row) not in (old, old | metadata)
                    or type(row["running"]) is not bool or type(row["slots"]) is not int
                    or row["slots"] < 1):
                raise ValueError("invalid heavy queue entry")
            if set(row) != old:
                if (any(type(row[key]) is not str for key in ("job", "command", "namespace"))
                        or type(row["pid"]) is not int or row["pid"] < 1
                        or row["host_namespace"] is not None and type(row["host_namespace"]) is not str
                        or row["host_pid"] is not None
                        and (type(row["host_pid"]) is not int or row["host_pid"] < 1)
                        or row["running"] and (type(row["started_at"]) is not str
                                               or type(row["started_ns"]) is not int
                                               or row["started_ns"] < 0)):
                    raise ValueError("invalid heavy holder metadata")
                if row["running"] and row["host_pid"] is None:
                    row["host_pid"] = resolve_host_pid(row)
                    if row["host_pid"] is not None:
                        write_request(fd, row)
            result.append((path, row))
        finally:
            os.close(fd)
    return result


@dataclass(frozen=True)
class Status:
    summary: str
    warning: str
    sample: Pressure | None
    queued_jobs: frozenset[str] = frozenset()


def status(previous=None):
    queued_jobs = frozenset()
    try:
        waiting = active = 0
        if directory().exists():
            folder = prepare()
            with gate(folder):
                rows = entries(folder)
                active = sum(row["running"] for _, row in rows)
                waiting = len(rows) - active
                queued_jobs = frozenset(row["job"] for _, row in rows
                                        if not row["running"] and row.get("job"))
        host = pressure(previous)
        reason = wait_reason(host, limits(host))
        summary = (f"host: available={host.available / MIB:.0f}MiB load1={host.load:.2f} "
                   f"headroom={host.headroom / MIB:.0f}MiB heavy_running={active} heavy_queued={waiting}")
        for group in host.groups:
            if group.path.name != "codex.slice" and group.maximum is None and group.cpus is None:
                continue
            memory = f"{group.current / MIB:.0f}" if group.current is not None else "unavailable"
            maximum = f"{group.maximum / MIB:.0f}" if group.maximum is not None else "max"
            cpu = f"{group.cpus:g}" if group.cpus is not None else "unavailable/unlimited"
            summary += (f" | {group.path.name}: memory={memory}/{maximum}MiB oom_kill={group.oom_kill} "
                        f"cpu_quota={cpu} usage_usec={group.usage_usec} "
                        f"throttled_usec={group.throttled_usec}")
        if not host.groups:
            summary += " cgroup_v2=unavailable"
        return Status(summary, reason, host, queued_jobs)
    except (OSError, ValueError, KeyError, IndexError, RuntimeError) as exc:
        return Status(f"host: pressure unavailable ({exc})",
                      "pressure unavailable; admission fails closed", None, queued_jobs)


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
                                       text=True, timeout=5, env=command_env()).stdout
            # Before this option existed, scope mode passed argv directly to execve.
            if "--expand-environment=" in help_text:
                prefix.insert(1, "--expand-environment=no")
            if subprocess.run([*prefix, "--", "/usr/bin/true"],
                              capture_output=True, timeout=5, env=command_env()).returncode == 0:
                return prefix
    except (OSError, subprocess.SubprocessError):
        pass
    print("heavy: systemd user scope unavailable; continuing WITHOUT requested memory cap", file=sys.stderr)
    return []


def run(command, memory_max=None):
    if not command:
        raise ValueError("heavy needs a command after --")
    if os.environ.get("AGENT_BRIDGE_HEAVY_ACTIVE"):
        raise RuntimeError("nested heavy commands would deadlock; wrap the outer command only")
    host = pressure()
    # Moving a worker into a sibling scope would discard its inherited per-job caps.
    inherited = host.slice is not None or any(g.maximum is not None for g in host.groups)
    if memory_max and inherited:
        if not memory_max.isdecimal() or int(memory_max) < 1:
            raise ValueError("--memory-max-mib must be a positive integer")
        if host.capacity > int(memory_max) * MIB:
            print("heavy: cannot tighten inherited cgroup here; "
                  "keeping EXISTING cap, requested cap not applied", file=sys.stderr)
        else:
            print("heavy: inherited cgroup already enforces the requested cap or tighter", file=sys.stderr)
    # Standalone commands may enter a scope before acquiring any lock descriptors.
    prefix = scope_prefix(memory_max) if not inherited else []
    if prefix:
        inner = [sys.executable, "-m", "agent_bridge.cli", "heavy", "--", *command]
        os.execvpe(prefix[0], [*prefix, "--", *inner], command_env())
    policy = limits(host)
    folder = prepare()
    path = folder / f"{time.time_ns():020d}-{uuid.uuid4().hex}.request"
    fd = None
    try:
        with gate(folder):
            rows = entries(folder)
            if any(row["slots"] != policy.slots for _, row in rows):
                raise RuntimeError("heavy slots differ from live requests; drain queue before changing slots")
            fd = locked_file(path)
            fcntl.flock(fd, fcntl.LOCK_EX)
            namespace = os.readlink(PROC / "self/ns/pid")
            host_namespace = os.environ.get("AGENT_BRIDGE_HOST_PID_NAMESPACE")
            if not host_namespace and not os.environ.get("AGENT_BRIDGE_WORKER"):
                host_namespace = namespace
            request = {"running": False, "slots": policy.slots,
                       "job": os.environ.get("AGENT_BRIDGE_JOB", ""),
                       "command": Path(command[0]).name, "pid": os.getpid(), "namespace": namespace,
                       "host_namespace": host_namespace,
                       "host_pid": os.getpid() if namespace == host_namespace else None,
                       "started_at": None, "started_ns": None}
            write_request(fd, request)
        queued_at = time.monotonic()
        last, reported = None, 0
        if host.groups:
            time.sleep(1)  # first CPU sample needs an interval, not a lifetime-average guess
        while True:
            host = pressure(host)
            with gate(folder):
                dead = []
                rows = entries(folder, path, dead)
                waiting = [p for p, row in rows if not row["running"]]
                position = waiting.index(path) + 1
                active = sum(row["running"] for _, row in rows)
                reason = wait_reason(host, policy)
                if position == 1 and active < policy.slots and not reason:
                    request.update(running=True, started_at=stamp(), started_ns=time.monotonic_ns())
                    write_request(fd, request)
                    break
            message = f"queue position {position}/{len(waiting)}; {active}/{policy.slots} slots busy"
            if position > 1 and active < policy.slots and not reason:
                # A free slot goes to the oldest request, which claims it on its next 1 s poll.
                ahead = dict(rows)[waiting[0]].get("job") or "standalone"
                message += f"; free slot is going to the earlier request ({ahead})"
            if reason:
                message += f"; {reason}"
            for _, holder in rows:
                if holder["running"]:
                    elapsed = (max(0, (time.monotonic_ns() - holder["started_ns"]) // 1000000000)
                               if holder.get("started_ns") is not None else 0)
                    message += (f"; holder={holder.get('job') or 'standalone'} "
                                f"command={holder.get('command') or 'unknown'} elapsed={elapsed}s "
                                f"alive=yes (kernel lock) host_pid={holder.get('host_pid') or 'unavailable'}")
            now = time.monotonic()
            if dead:
                print("heavy: holder alive=no; cleared dead holder record", file=sys.stderr, flush=True)
            if now - queued_at >= 1800:
                message += "; wait exceeds 30 minutes; report this to the coordinator"
            state = (position, len(waiting), active, reason,
                     tuple(p.name for p, row in rows if row["running"]))
            if (state != last and now - reported >= 5) or last is None or now - reported >= 30:
                print(f"heavy: waiting, {message}; normal queue wait: do not report unless the holder "
                      "is dead or the wait exceeds 30m", file=sys.stderr, flush=True)
                last, reported = state, now
            time.sleep(1)
        print(f"heavy: admitted; headroom={host.headroom / MIB:.0f}MiB load1={host.load:.2f}",
              file=sys.stderr, flush=True)
        os.set_inheritable(fd, True)
        # Replace the wrapper: signals, stdio and exit status belong directly to the command.
        os.execvpe(command[0], command, {**command_env(), "AGENT_BRIDGE_HEAVY_ACTIVE": "1"})
    finally:
        if fd is not None:
            os.close(fd)
        with gate(folder):
            path.unlink(missing_ok=True)

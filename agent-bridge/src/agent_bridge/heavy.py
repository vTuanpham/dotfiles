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

from .resources import MIB, Pressure, limits, pressure, wait_reason


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


@contextmanager
def gate(folder):
    fd = locked_file(folder / "gate.lock")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def entries(folder, own=None):
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
                    path.unlink()
                    continue
            row = json.loads(os.read(fd, 4096))
            if (type(row) is not dict or set(row) != {"running", "slots"}
                    or type(row["running"]) is not bool or type(row["slots"]) is not int
                    or row["slots"] < 1):
                raise ValueError("invalid heavy queue entry")
            result.append((path, row))
        finally:
            os.close(fd)
    return result


@dataclass(frozen=True)
class Status:
    summary: str
    warning: str
    sample: Pressure | None


def status(previous=None):
    try:
        host = pressure(previous)
        reason = wait_reason(host, limits(host))
        waiting = active = 0
        if directory().exists():
            folder = prepare()
            with gate(folder):
                rows = entries(folder)
                active = sum(row["running"] for _, row in rows)
                waiting = len(rows) - active
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
        return Status(summary, reason, host)
    except (OSError, ValueError, KeyError, IndexError, RuntimeError) as exc:
        return Status(f"host: pressure unavailable ({exc})",
                      "pressure unavailable; admission fails closed", None)


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
        os.execvp(prefix[0], [*prefix, "--", *inner])
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
            os.write(fd, json.dumps({"running": False, "slots": policy.slots}).encode())
        last, reported = None, 0
        if host.groups:
            time.sleep(1)  # first CPU sample needs an interval, not a lifetime-average guess
        while True:
            host = pressure(host)
            with gate(folder):
                rows = entries(folder, path)
                waiting = [p for p, row in rows if not row["running"]]
                position = waiting.index(path) + 1
                active = sum(row["running"] for _, row in rows)
                reason = wait_reason(host, policy)
                if position == 1 and active < policy.slots and not reason:
                    os.lseek(fd, 0, os.SEEK_SET)
                    os.ftruncate(fd, 0)
                    os.write(fd, json.dumps({"running": True, "slots": policy.slots}).encode())
                    break
            message = f"queue position {position}/{len(waiting)}; {active}/{policy.slots} slots busy"
            if reason:
                message += f"; {reason}"
            now = time.monotonic()
            if (message != last and now - reported >= 5) or last is None or now - reported >= 30:
                print(f"heavy: waiting, {message}", file=sys.stderr, flush=True)
                last, reported = message, now
            time.sleep(1)
        print(f"heavy: admitted; headroom={host.headroom / MIB:.0f}MiB load1={host.load:.2f}",
              file=sys.stderr, flush=True)
        os.set_inheritable(fd, True)
        # Replace the wrapper: signals, stdio and exit status belong directly to the command.
        os.execvpe(command[0], command, {**os.environ, "AGENT_BRIDGE_HEAVY_ACTIVE": "1"})
    finally:
        if fd is not None:
            os.close(fd)
        with gate(folder):
            path.unlink(missing_ok=True)

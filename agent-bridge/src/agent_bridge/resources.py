"""Read-only Linux host and inherited cgroup v2 budgets; never move or limit processes."""

import math
import os
import re
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

MIB = 1024 * 1024
PROC = Path("/proc")
CGROUP = Path("/sys/fs/cgroup")


def counters(path):
    values = {}
    for line in path.read_text().splitlines():
        key, value = line.split()
        if key in values or not value.isdecimal():
            raise ValueError(f"invalid cgroup counters: {path.name}")
        values[key] = int(value)
    return values


def number(path):
    value = path.read_text().strip()
    if not value.isdecimal():
        raise ValueError(f"invalid cgroup counter: {path.name}")
    return int(value)


def cgroup_paths():
    membership = PROC / "self/cgroup"
    if not membership.exists():
        return []
    unified = [line[3:] for line in membership.read_text().splitlines() if line.startswith("0::")]
    if not unified:  # cgroup v1: host-only admission, explicitly labelled in status
        return []
    if len(unified) != 1 or not unified[0].startswith("/") or ".." in Path(unified[0]).parts:
        raise ValueError("invalid cgroup v2 membership")
    current = CGROUP / unified[0].lstrip("/")
    # A root outside codex.slice must still see the shared worker budget.
    shared = CGROUP / f"user.slice/user-{os.getuid()}.slice/user@{os.getuid()}.service/codex.slice"
    paths = []
    for leaf in (current, shared if shared.exists() else current):
        while leaf != CGROUP:
            if leaf not in paths:
                paths.append(leaf)
            leaf = leaf.parent
    return paths


@dataclass(frozen=True)
class Group:
    path: Path
    current: int | None
    maximum: int | None
    oom_kill: int | None
    cpus: float | None
    usage_usec: int
    throttled_usec: int | None
    nr_throttled: int | None
    cpu_fraction: float | None
    throttled: bool


@dataclass(frozen=True)
class Pressure:
    total: int
    available: int
    load: float
    at: float
    groups: tuple[Group, ...]

    @property
    def capacity(self):
        return min([self.total, *[g.maximum for g in self.groups if g.maximum is not None]])

    @property
    def headroom(self):
        return min([self.available, *[max(0, g.maximum - g.current) for g in self.groups
                                     if g.maximum is not None]])

    @property
    def slice(self):
        return next((g for g in self.groups if g.path.name == "codex.slice"), None)

    @property
    def shared_groups(self):
        return tuple(g for g in self.groups if not self.slice or self.slice.path.is_relative_to(g.path))

    @property
    def shared_capacity(self):
        return min([self.total, *[g.maximum for g in self.shared_groups if g.maximum is not None]])

    @property
    def shared_headroom(self):
        return min([self.available, *[max(0, g.maximum - g.current) for g in self.shared_groups
                                     if g.maximum is not None]])


def pressure(previous=None):
    memory = {}
    for line in (PROC / "meminfo").read_text().splitlines():
        key, _, value = line.partition(":")
        if key in {"MemTotal", "MemAvailable"}:
            fields = value.split()
            if key in memory or len(fields) != 2 or fields[1] != "kB":
                raise ValueError("invalid /proc/meminfo")
            memory[key] = int(fields[0]) * 1024
    total, available = memory["MemTotal"], memory["MemAvailable"]
    fields = (PROC / "loadavg").read_text().split()
    if not fields:
        raise ValueError("empty /proc/loadavg")
    load = float(fields[0])
    if not 0 <= available <= total or total <= 0 or not math.isfinite(load) or load < 0:
        raise ValueError("invalid host pressure readings")
    at = time.clock_gettime(time.CLOCK_MONOTONIC)
    before = {g.path: g for g in previous.groups} if previous else {}
    groups = []
    for path in cgroup_paths():
        current = maximum = oom = cpus = None
        if (path / "memory.max").exists():
            maximum = (None if (path / "memory.max").read_text().strip() == "max"
                       else number(path / "memory.max"))
            current = number(path / "memory.current")
            oom = counters(path / "memory.events")["oom_kill"]
        if (path / "cpu.max").exists():
            quota, period = (path / "cpu.max").read_text().split()
            if not period.isdecimal() or int(period) <= 0:
                raise ValueError("invalid cgroup CPU period")
            if quota != "max":
                if not quota.isdecimal() or int(quota) <= 0:
                    raise ValueError("invalid cgroup CPU quota")
                cpus = int(quota) / int(period)
        cpu = counters(path / "cpu.stat")
        fraction, throttled = None, False
        old = before.get(path)
        if old and at - previous.at >= 0.5:
            if cpus is not None and cpu["usage_usec"] >= old.usage_usec:
                fraction = (cpu["usage_usec"] - old.usage_usec) / ((at - previous.at) * 1e6 * cpus)
            throttled = (old.nr_throttled is not None
                         and cpu.get("nr_throttled", 0) > old.nr_throttled)
        groups.append(Group(path, current, maximum, oom, cpus, cpu["usage_usec"],
                            cpu.get("throttled_usec"), cpu.get("nr_throttled"), fraction, throttled))
    return Pressure(total, available, load, at, tuple(groups))


@dataclass(frozen=True)
class Limits:
    slots: int | None
    available: int
    load: float


def limits(host):
    try:
        slot_value = os.environ.get("AGENT_BRIDGE_HEAVY_SLOTS")
        slots = int(slot_value) if slot_value is not None else None
        available = int(os.environ.get("AGENT_BRIDGE_HEAVY_MIN_AVAILABLE_MIB",
                                       str(max(1024, math.ceil(host.capacity / MIB / 5))))) * MIB
        load = float(os.environ.get("AGENT_BRIDGE_HEAVY_MAX_LOAD", str((os.cpu_count() or 1) * 0.8)))
    except ValueError:
        raise ValueError("invalid AGENT_BRIDGE_HEAVY_SLOTS, AGENT_BRIDGE_HEAVY_MIN_AVAILABLE_MIB "
                         "or AGENT_BRIDGE_HEAVY_MAX_LOAD; expected numeric limits") from None
    if (slots is not None and slots < 1) or available < 0 or not math.isfinite(load) or load <= 0:
        raise ValueError("heavy limits need positive slots/load and nonnegative available memory")
    return Limits(slots, available, load)


def wait_reason(host, policy, shared=False):
    reasons = []
    headroom = host.shared_headroom if shared else host.headroom
    if headroom < policy.available:
        reasons.append(f"available memory headroom {headroom / MIB:.0f} MiB < "
                       f"{policy.available / MIB:.0f} MiB (host and inherited cgroups)")
    if host.load >= policy.load:
        reasons.append(f"load1 {host.load:.2f} >= {policy.load:g}")
    for group in host.shared_groups if shared else host.groups:
        if group.throttled or group.cpu_fraction is not None and group.cpu_fraction >= 0.8:
            reasons.append(f"{group.path.name} CPU busy/throttled")
    return "; ".join(reasons)


def memory_size(value):
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([KMGT]?)", value)
    if not match:
        raise ValueError("memory size must be positive bytes or K/M/G/T, such as 1G or 2500M")
    numerator, denominator = Decimal(match[1]).as_integer_ratio()
    size, remainder = divmod(numerator * 1024 ** (" KMGT".index(match[2]) if match[2] else 0), denominator)
    if size <= 0 or remainder:
        raise ValueError("memory size must be a positive whole number of bytes")
    return size


def validate_caps(memory, cpu):
    """Validate per-job limits against the shared slice/ancestors, never the calling job's scope."""
    host = pressure()
    size = memory_size(memory)
    quota = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)%", cpu)
    if not quota or Decimal(quota[1]) <= 0:
        raise ValueError("memory and CPU caps must be positive; CPU uses a percentage such as 400%")
    ancestors = [g for g in host.groups if host.slice and host.slice.path.is_relative_to(g.path)]
    memory_max = min([host.total, *[g.maximum for g in ancestors if g.maximum is not None]])
    cpu_max = min([float(os.cpu_count() or 1), *[g.cpus for g in ancestors if g.cpus is not None]])
    if size > memory_max:
        raise ValueError(f"memory cap exceeds effective slice/host limit ({memory_max / MIB:.0f} MiB)")
    if Decimal(quota[1]) > Decimal(str(cpu_max)) * 100:
        raise ValueError(f"CPU cap exceeds effective slice/host limit ({cpu_max * 100:g}%)")

"""Observe worker scopes, using the resource module's strict Linux boundary readers."""

from agent_resources import resources


def scopes(pids):
    found = set()
    for pid in pids:
        try:
            paths = resources.cgroup_paths(pid, include_shared=False)
            if paths and paths[0].name.endswith(".scope") and any(
                p.name == resources.slice_name() for p in paths
            ):
                found.add(paths[0])
        except (OSError, ValueError):
            continue
    return found


def memory(pids):
    """RSS is only a fallback when a job has no readable scope; shared pages can count twice."""
    total = 0
    for pid in pids:
        try:
            rows = (resources.PROC / str(pid) / "status").read_text().splitlines()
            values = [line.split()[1:] for line in rows if line.startswith("VmRSS:")]
            if not values:  # a process exited between tree and RSS reads
                continue
            if len(values) != 1 or len(values[0]) != 2 or values[0][1] != "kB":
                return None
            value = int(values[0][0])
            if value < 0:
                return None
            total += value * 1024
        except (OSError, ValueError):
            return None
    return total


def scope_memory(path):
    return resources.number(path / "memory.current"), resources.counters(path / "memory.events")["oom_kill"]

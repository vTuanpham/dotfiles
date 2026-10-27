"""Locked OOM observations survive short-lived CLI readers and worker exits."""

import fcntl
import json
import os
from dataclasses import replace
from pathlib import Path

from .core import save


def observe(folder, groups, jobs):
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    if folder.is_symlink() or folder.stat().st_uid != os.getuid() or folder.stat().st_mode & 0o077:
        raise ValueError("status observation directory must be private and owned")
    fd = os.open(folder / "lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        path = folder / "oom.json"
        old = {}
        if path.exists():
            if path.is_symlink() or path.stat().st_size > 1048576:
                raise ValueError("unsafe status observations")
            data = json.loads(path.read_text())
            if (
                type(data) is not dict
                or type(data.get("schema_version")) is not int
                or data["schema_version"] != 1
                or type(data.get("groups")) is not dict
            ):
                raise ValueError("invalid status observations")
            old = data["groups"]
            for key, row in old.items():
                if (
                    type(key) is not str
                    or type(row) is not dict
                    or set(row) != {"total", "job"}
                    or type(row["total"]) is not int
                    or row["total"] < 0
                    or row["job"] is not None
                    and type(row["job"]) is not str
                ):
                    raise ValueError("invalid status observation counter")
        current = {key: row for key, row in old.items() if row["job"] in jobs}
        result, deltas = [], {}
        for group in groups:
            # The scope inode distinguishes a later scope that happens to reuse its pathname.
            try:
                identity = f"{group.id}:{Path(group.id).stat().st_ino}"
            except OSError:
                identity = group.id
            if group.attributed_job is None:
                identity += ":sample"  # an unattributed read cannot overwrite historical job attribution
            before = old.get(identity)
            delta = (
                max(0, group.oom_kill - before["total"])
                if before is not None and group.oom_kill is not None
                else None
            )
            owner = group.attributed_job
            if group.oom_kill is not None:
                current[identity] = {"total": group.oom_kill, "job": owner}
            result.append(replace(group, oom_kill_delta=delta))
            if owner:
                deltas.setdefault(owner, []).append(delta)
        totals = {}
        for row in current.values():
            if row["job"] in jobs:
                totals[row["job"]] = totals.get(row["job"], 0) + row["total"]
        changes = {
            job: sum(values) if all(v is not None for v in values) else None for job, values in deltas.items()
        }
        save(path, {"schema_version": 1, "groups": current})
        return tuple(result), totals, changes
    finally:
        os.close(fd)

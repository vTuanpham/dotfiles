"""Retirement keeps job paths stable so backend homes and native sessions survive."""

import json
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone

from . import status
from .core import append, command_env, human, load_state, lock_runner, save, stamp, tree_size


def purge_due(state, now=None):
    if not state.get("retiredAt"):
        return False
    try:
        retired = datetime.fromisoformat(state["retiredAt"])
        after = datetime.fromisoformat(state["purgeAfter"])
        if retired.tzinfo is None or after.tzinfo is None or after < retired:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise RuntimeError("invalid retirement dates; refusing to purge") from None
    return after <= (now or datetime.now(timezone.utc))


def _purge(job):
    freed = tree_size(job)
    wt = job / "out/wt"
    if not (job / "out").is_symlink() and not wt.is_symlink() and (wt / ".git").exists():
        status = subprocess.run(["git", "-C", str(wt), "status", "--porcelain"],
                                env=command_env(), capture_output=True)
        if status.returncode or status.stdout:
            raise RuntimeError("worktree is dirty or unreadable; refusing to purge")
        removed = subprocess.run(["git", "-C", str(wt), "worktree", "remove", str(wt)],
                                 env=command_env(), capture_output=True)
        if removed.returncode:
            raise RuntimeError("could not remove clean worktree; refusing to purge")
    shutil.rmtree(job)
    return f"purged {job.parent.name}/{job.name}, freed {human(freed)}"


def retire(job, archive, read_report, keep_days=14, purge=False):
    if keep_days < 1:
        raise RuntimeError("--keep-days must be at least 1")
    fd = lock_runner(job)
    try:
        state = load_state(job)
        if status.running(state):
            raise RuntimeError("job has a live runner; stop it before retiring")
        if not state.get("retiredAt"):
            retired = stamp()
            try:
                after = (datetime.fromisoformat(retired) + timedelta(days=keep_days)).isoformat()
            except OverflowError:
                raise RuntimeError("--keep-days is too large") from None
            archive.parent.mkdir(parents=True, exist_ok=True)
            append(archive, {
                "at": retired, "job": f"{job.parent.name}/{job.name}",
                "backend": state.get("backend"), "model": state.get("model"), "title": state.get("title"),
                "prompt": (job / "prompt.md").read_text(encoding="utf-8")[:300]
                if (job / "prompt.md").exists() else "",
                "final": read_report(job)[:2000], "retiredAt": retired, "purgeAfter": after,
            })
            state.update(retiredAt=retired, purgeAfter=after)
            save(job / "state.json", state)
        if purge:
            return _purge(job)
        return (f"retired {job.parent.name}/{job.name}; purge after {state['purgeAfter']}; "
                f"restore with agent-bridge restore {job.parent.name}/{job.name}")
    finally:
        os.close(fd)


def restore(job):
    if not (job / "state.json").is_file():
        raise RuntimeError("job data is missing or was purged; cannot restore "
                           "(archived reports contain no session)")
    fd = lock_runner(job)
    try:
        state = load_state(job)
        if status.running(state):
            raise RuntimeError("job has a live runner; stop it before restoring")
        state.pop("retiredAt", None)
        state.pop("purgeAfter", None)
        save(job / "state.json", state)
        return f"restored {job.parent.name}/{job.name}; resume uses the same session"
    finally:
        os.close(fd)


def purge(job):
    fd = lock_runner(job)
    try:
        state = load_state(job)
        if status.running(state):
            raise RuntimeError("job has a live runner; stop it before purging")
        if not purge_due(state):
            raise RuntimeError("job is not eligible for purge; use retire --purge for immediate deletion")
        return _purge(job)
    finally:
        os.close(fd)


def archived_result(archive, name):
    result = None
    if archive.exists():
        with archive.open(encoding="utf-8") as lines:
            for line in lines:
                try:
                    row = json.loads(line)
                    if isinstance(row, dict) and row.get("job") == name and isinstance(row.get("final"), str):
                        result = row["final"]
                except json.JSONDecodeError:
                    continue
    if result is None:
        raise RuntimeError("job and archived report not found")
    return result

"""The dated reference (guide/models.md) and the lock that records what it was written against.

`stale` compares the live model lists with the lock and caches the answer; `start` only reads that cache
and the lock's date, so a run never waits on a model listing."""

import contextlib
import io
import json
from datetime import date
from pathlib import Path

from . import agy, codex, opencode
from .core import HOME

GUIDES = Path(__file__).with_name("guide")
LOCK = GUIDES / "models.lock"  # "refreshed <date>", then one "<backend> <model id>" line per model covered
CACHE = HOME / "stale.json"
PENDING = HOME / "refresh" / "pending"  # holds the directory of a proposal waiting for the user
MAX_AGE_DAYS = 30
LISTERS = {"codex": codex.models, "agy": lambda: agy.models("a1"), "opencode": opencode.models}
ONLY = {"opencode": "opencode/"}  # the free tier is what the reference covers, not every provider


def read_lock():
    """(date the reference was last checked or None, {backend: set of model ids})."""
    refreshed, ids = None, {}
    for line in LOCK.read_text(encoding="utf-8").splitlines() if LOCK.is_file() else []:
        key, _, value = line.partition(" ")
        if key == "refreshed":
            refreshed = date.fromisoformat(value)
        elif value:
            ids.setdefault(key, set()).add(value)
    return refreshed, ids


def live():
    """{backend: model ids it lists now}; a backend that is missing or signed out is left out."""
    found = {}
    for name, lister in LISTERS.items():
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                lister()
        except (Exception, SystemExit):  # noqa: BLE001 - not installed, not signed in: nothing to compare
            continue
        ids = {line.split("\t")[0] for line in out.getvalue().splitlines() if line}
        found[name] = {i for i in ids if i.startswith(ONLY.get(name, ""))}
    return found


def trusted(found, locked):
    """Drop a listing that shares no model with the lock: a listing that failed, not a lineup that retired."""
    return {name: ids for name, ids in found.items() if ids and (not locked.get(name) or ids & locked[name])}


def accept(today=None):
    """Record the live lists as reviewed against the reference."""
    _, locked = read_lock()
    known = {**locked, **trusted(live(), locked)}  # a backend whose listing failed keeps its old entries
    lines = [f"refreshed {today or date.today()}"]
    lines += [f"{name} {i}" for name, ids in sorted(known.items()) for i in sorted(ids)]
    LOCK.write_text("\n".join(lines) + "\n", encoding="utf-8")


def old():
    """True when the reference's last check is missing or past MAX_AGE_DAYS."""
    refreshed, _ = read_lock()
    return refreshed is None or (date.today() - refreshed).days > MAX_AGE_DAYS


def drift():
    """Model ids that appeared or vanished since the lock was written, one line per backend."""
    _, locked = read_lock()
    found = []
    for name, ids in trusted(live(), locked).items():
        new, gone = sorted(ids - locked.get(name, set())), sorted(locked.get(name, set()) - ids)
        parts = ([f"new {', '.join(new)}"] if new else []) + ([f"gone {', '.join(gone)}"] if gone else [])
        if parts:
            found.append(f"{name}: " + "; ".join(parts))
    return found


def check():
    """Every reason to doubt the reference; also caches the model drift for `start` to mention."""
    changed = drift()
    HOME.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps({"on": str(date.today()), "drift": changed}))
    refreshed, _ = read_lock()
    age = [f"the reference was last checked {refreshed or 'never'} (limit {MAX_AGE_DAYS} days)"] * old()
    waiting = []
    if PENDING.is_file():
        waiting = [f"a proposal is waiting; report: {Path(PENDING.read_text()) / 'report.md'}"]
    return age + changed + waiting


def warning():
    """One line for stderr when a run should mention the reference, else None. Reads files only."""
    notes = []
    if old():
        notes.append("the model and plan reference is past its check date")
    try:
        if json.loads(CACHE.read_text())["drift"]:
            notes.append("the live model lists changed since it was written")
    except (OSError, ValueError, KeyError):
        pass
    if PENDING.is_file():
        notes.append("a refreshed reference is waiting for a root to re-check and apply it")
    if not notes:
        return None
    return (
        "agent-bridge: " + "; ".join(notes)
        + '. See `agent-bridge guide workflow`, "Keeping the reference current".'
    )

"""The dated model/subscription guides and their shared review lock.

`stale` compares the live model lists with the lock and caches the answer; `start` only reads that cache
and the lock's date, so a run never waits on a model listing."""

import contextlib
import hashlib
import io
import json
from datetime import date
from pathlib import Path

from . import agy, codex, opencode
from .core import HOME

GUIDES = Path(__file__).with_name("guide")
DOCUMENTS = ("models.md", "subscriptions.md")
LOCK = GUIDES / "models.lock"  # refreshed <date>; guide <file> <sha256>; <backend> <model id>
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
        elif key != "guide" and value:
            ids.setdefault(key, set()).add(value)
    return refreshed, ids


def guide_hashes():
    return {name: hashlib.sha256((GUIDES / name).read_bytes()).hexdigest() for name in DOCUMENTS}


def guide_drift():
    locked = {}
    for line in LOCK.read_text().splitlines() if LOCK.is_file() else []:
        if line.startswith("guide "):
            _, name, digest = line.split()
            locked[name] = digest
    return [f"guide {name}: changed since review" for name, digest in guide_hashes().items()
            if locked.get(name) != digest]


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


def accept(today=None, found=None):
    """Record the live lists as reviewed against the reference."""
    _, locked = read_lock()
    known = {**locked, **trusted(live() if found is None else found, locked)}
    lines = [f"refreshed {today or date.today()}"]
    lines += [f"guide {name} {digest}" for name, digest in guide_hashes().items()]
    lines += [f"{name} {i}" for name, ids in sorted(known.items()) for i in sorted(ids)]
    LOCK.write_text("\n".join(lines) + "\n", encoding="utf-8")


def old():
    """True when the reference's last check is missing or past MAX_AGE_DAYS."""
    refreshed, _ = read_lock()
    return refreshed is None or (date.today() - refreshed).days > MAX_AGE_DAYS


def inspect():
    """Read-only structured drift, shared by refresh --check and stale."""
    refreshed, locked = read_lock()
    age = (date.today() - refreshed).days if refreshed else None
    stale_guides = [line.split()[1].rstrip(":") for line in guide_drift()]
    if age is None or age > MAX_AGE_DAYS:
        stale_guides = list(DOCUMENTS)
    models = {name: {"new": sorted(ids - locked.get(name, set())),
                     "gone": sorted(locked.get(name, set()) - ids)}
              for name, ids in trusted(live(), locked).items()}
    return {"refreshed": str(refreshed) if refreshed else None, "age_days": age,
            "max_age_days": MAX_AGE_DAYS, "stale_guides": stale_guides, "models": models}


def render(data):
    """Human rendering of inspect(), without another live query."""
    found = [f"guide {name}: changed or past review date" for name in data["stale_guides"]]
    for name, changes in data["models"].items():
        parts = [f"{kind} {', '.join(changes[kind])}" for kind in ("new", "gone") if changes[kind]]
        if parts:
            found.append(f"{name}: " + "; ".join(parts))
    return found


def drift():
    """Document and model changes, excluding age (which has a separate warning)."""
    data = inspect()
    return guide_drift() + render({**data, "stale_guides": []})


def check():
    """Every reason to doubt the reference; also caches the model drift for `start` to mention."""
    data = inspect()
    changed = render(data)
    HOME.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps({"on": str(date.today()),
                                 "drift": render({**data, "stale_guides": []})}))
    waiting = []
    if PENDING.is_file():
        waiting = [f"a proposal is waiting; report: {Path(PENDING.read_text()) / 'report.md'}"]
    return changed + waiting


def warning():
    """One line for stderr when a run should mention the reference, else None. Reads files only."""
    notes = []
    if old():
        notes.append("the model and subscription guides are past their check date")
    if guide_drift():
        notes.append("the guide files changed since review")
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

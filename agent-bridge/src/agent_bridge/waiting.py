"""Worker-owned bounded declarations; serialized with runner state writes."""

import re
import time
from dataclasses import asdict

from . import core
from .assessment import MAX_DECLARED_WAIT_SECONDS
from .status_inputs import timestamp
from .status_model import DeclaredWait

KINDS = ("command", "peer", "root", "external", "dependency")


def decode(value, owner, now=None):
    if not isinstance(value, dict) or set(value) != {
        "kind", "note", "declared_at", "expected_seconds", "peer"
    }:
        raise ValueError("invalid waiting record")
    if value["kind"] not in KINDS:
        raise ValueError("unknown wait kind")
    note = value["note"]
    if not isinstance(note, str) or len(note) > 80 or any(ord(c) < 32 or ord(c) == 127 for c in note):
        raise ValueError("wait note must be at most 80 printable characters")
    if timestamp(value["declared_at"]) > (time.time() if now is None else now):
        raise ValueError("wait declaration cannot be in the future")
    seconds = value["expected_seconds"]
    if type(seconds) is not int or not 1 <= seconds <= MAX_DECLARED_WAIT_SECONDS:
        raise ValueError("wait duration must be between 1 second and 2 hours")
    peer = value["peer"]
    if peer is not None and (value["kind"] not in {"peer", "dependency"}
                             or not isinstance(peer, str)
                             or not re.fullmatch(re.escape(owner) + r"/[A-Za-z0-9][A-Za-z0-9_.-]*", peer)):
        raise ValueError("peer must name a sibling job")
    return DeclaredWait(**value)


def write(job, value):
    with core.state_lock(job):
        state = core.load_state(job)
        if value is None:
            if "waiting" not in state:
                return
            state.pop("waiting", None)
        else:
            decode(asdict(value), job.parent.name)
            state["waiting"] = asdict(value)
        core.atomic_save(job / "state.json", state)


def clear(job):
    if (job / "state.json").exists():
        write(job, None)


def notice(job, assessment):
    """Claim informational notices across concurrent watches and runner restarts."""
    with core.state_lock(job):
        state = core.load_state(job)
        seen = state.get("assessment_notices", [])
        if (not isinstance(seen, list) or len(seen) > 128
                or any(not isinstance(item, str) or len(item) > 1024 for item in seen)):
            raise ValueError("invalid assessment notice ledger")
        if assessment.notice_id in seen:
            return
        state["assessment_notices"] = [*seen, assessment.notice_id][-128:]
        core.atomic_save(job / "state.json", state)
        core.log(job, assessment.state.replace("-", "_"), level="info",
                 noticeId=assessment.notice_id, message=assessment.reason)

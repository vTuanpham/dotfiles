"""Optional launcher provenance, joined only by exact native harness/session identity."""

import shutil
import subprocess
from pathlib import Path

from .models import decode_json, fields, text

BACKENDS = {"codex": "Codex", "claude": "Claude", "agy": "Antigravity", "opencode": "OpenCode"}


def identity(value):
    fields(value, ("backend", "session_id"))
    if value["backend"] not in BACKENDS:
        raise ValueError("Unknown launcher harness")
    return value["backend"], text(value["session_id"], "native session identity", 200)


def decode(value):
    fields(value, ("version", "sessions"))
    if type(value["version"]) is not int or value["version"] != 1 or type(value["sessions"]) is not list:
        raise ValueError("Unsupported launcher metadata")
    result = {}
    for row in value["sessions"]:
        fields(row, ("backend", "session_id", "job", "title", "parent"))
        key = identity({"backend": row["backend"], "session_id": row["session_id"]})
        job = text(row["job"], "launcher job", 400)
        if len(job.split("/")) != 2 or any(part in ("", ".", "..") for part in job.split("/")):
            raise ValueError("Invalid launcher job identity")
        if type(row["title"]) is not str or len(row["title"]) > 1000:
            raise ValueError("Invalid launcher title")
        parent = identity(row["parent"]) if row["parent"] is not None else None
        result.setdefault(key, []).append({"tool": "Agent Bridge", "job": job,
                                           "title": row["title"], "parent": parent})
    return {key: rows[0] for key, rows in result.items() if len(rows) == 1}


def read():
    command = shutil.which("agent-bridge")
    if command is None:
        candidate = Path.home() / ".local/bin/agent-bridge"
        if not candidate.is_file():
            return {}
        command = str(candidate)
    try:
        result = subprocess.run([command, "sessions"], capture_output=True, timeout=3)
        if result.returncode or len(result.stdout) > 2 * 1024 * 1024:
            return {}
        return decode(decode_json(result.stdout))
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        return {}  # Older or absent launchers do not prevent native session discovery.


def annotate(targets, rows, bindings):
    identities = {}
    for target in targets.values():
        key = (target.settings.get("bridge_backend", target.adapter), target.session_id)
        identities.setdefault(key, []).append(target.id)
    for row in rows:
        target = targets[row["id"]]
        key = (target.settings.get("bridge_backend", target.adapter), target.session_id)
        found = bindings.get(key)
        if found is None or len(identities[key]) != 1:
            continue
        parent = found["parent"]
        public_parent = None
        if parent is not None:
            matched = identities.get(parent, [])
            parent_target = targets[matched[0]] if len(matched) == 1 else None
            public_parent = {"harness": BACKENDS[parent[0]],
                             "id": parent_target.id if parent_target else None,
                             "label": parent_target.label if parent_target else None}
        row["origin"] = {**found, "parent": public_parent}

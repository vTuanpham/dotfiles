"""Claude root safety net. No backend calls, notifications or changes to jobs."""

import fcntl
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path


def waiting_for_user(payload):
    text = payload.get("last_assistant_message", "")
    if not isinstance(text, str):
        raise ValueError("invalid last assistant message")
    if "?" in text or re.search(
        r"(?im)\b(?:waiting for your|need your|please (?:choose|confirm|approve)|let me know)\b|"
        r"^\s*(?:choose|pick|select|which|what|would you|could you|shall I|should I|do you|can you)\b",
        text,
    ):
        return True
    path = Path(payload["transcript_path"]).expanduser()
    with path.open("rb") as stream:
        size = stream.seek(0, 2)
        stream.seek(max(0, size - 2 * 1024 * 1024))
        lines = stream.read().splitlines()
    if size > 2 * 1024 * 1024:
        lines = lines[1:]
    pending = set()
    for line in lines:
        row = json.loads(line)
        content = row.get("message", {}).get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and block.get("name") == "AskUserQuestion":
                pending.add(block["id"])
            if block.get("type") == "tool_result":
                pending.discard(block.get("tool_use_id"))
    return bool(pending)


def pending_set(payload, snapshot):
    if (payload.get("hook_event_name") != "Stop" or payload.get("agent_id")
            or payload.get("agent_transcript_path") or payload.get("stop_hook_active")
            or os.environ.get("AGENT_BRIDGE_WORKER") or waiting_for_user(payload)):
        return []
    if snapshot["schema_version"] != 1 or snapshot.get("errors"):
        return []  # incomplete observations must never prevent stopping
    owners = {o["id"] for o in snapshot["owners"] if o.get("root_backend") == "claude"
              and o.get("root_session_id") == payload["session_id"] and not o.get("active_watch", False)}
    pending = []
    for job in snapshot["jobs"]:
        if job["owner"] in owners and not job.get("retired_at"):
            if job["running"]:
                pending.append([job["id"], "running", job["log_identity"], job.get("started_at")])
    for event in snapshot["events"]:
        if event["kind"] != "turn_completed":
            continue
        job = next((j for j in snapshot["jobs"] if j["id"] == event["job"]), None)
        if job and not job.get("retired_at") and job["owner"] in owners and event["offset"] > max(
                job["acknowledged_through"], job["completed_through"]):
            pending.append([job["id"], "unread", event["id"]])
    return sorted(pending, key=lambda p: json.dumps(p))


def decide(payload, snapshot, folder):
    pending = pending_set(payload, snapshot)
    if not pending:
        return None
    signature = hashlib.sha256(json.dumps(pending, sort_keys=True).encode()).hexdigest()
    session = hashlib.sha256(payload["session_id"].encode()).hexdigest()
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    if folder.is_symlink() or folder.stat().st_mode & 0o077:
        return None
    with (folder / f"{session}.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = folder / f"{session}.json"
        previous = json.loads(path.read_text()) if path.exists() else []
        if type(previous) is not list or any(type(v) is not str for v in previous):
            return None
        if signature in previous:
            return None
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps([*previous, signature]))
        os.replace(temporary, path)
    jobs = sorted({p[0] for p in pending})
    owners = sorted({j.split("/")[0] for j in jobs})
    command = "agent-bridge watch " + " ".join(shlex.quote(o) for o in owners) + " --until-event"
    return {"decision": "block", "reason": f"arm `{command}` or acknowledge: {', '.join(jobs)}"}


def main():
    try:
        if os.environ.get("AGENT_BRIDGE_STOP_GUARD") == "0":
            return
        payload = json.load(sys.stdin)
        if payload.get("hook_event_name") == "SessionStart":
            if not payload.get("agent_id") and not os.environ.get("AGENT_BRIDGE_WORKER"):
                path = os.environ.get("CLAUDE_ENV_FILE")
                sid = payload.get("session_id")
                if path and type(sid) is str and re.fullmatch(r"[A-Za-z0-9_-]{1,200}", sid):
                    with open(path, "a") as stream:
                        stream.write(f"export CLAUDE_CODE_SESSION_ID={shlex.quote(sid)}\n")
            return
        if (payload.get("hook_event_name") != "Stop" or payload.get("agent_id")
                or payload.get("stop_hook_active") or os.environ.get("AGENT_BRIDGE_WORKER")):
            return
        result = subprocess.run(["agent-bridge", "status", "--json", "--no-quotas"],
                                capture_output=True, text=True, timeout=8)
        if result.returncode:
            return
        snapshot = json.loads(result.stdout)
        state = Path(os.environ.get("XDG_STATE_HOME", "~/.local/state")).expanduser()
        decision = decide(payload, snapshot, state / "agent-bridge/stop-guard")
        if decision:
            print(json.dumps(decision))
    except Exception:
        return  # any error, including malformed input, is permission to stop


if __name__ == "__main__":
    main()

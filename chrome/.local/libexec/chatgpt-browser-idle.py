"""Codex lifecycle hook: one advisory reminder after five idle minutes."""

import json
import os
from pathlib import Path
import sqlite3
import stat
import sys
import time


IDLE_SECONDS = 300
GUIDE = "~/dotfiles-with-agency/chrome/README.md#visible-agent-tabs"
TOOLS = {"mcp__node_repl__js", "mcp__node_repl__js_reset"}


def state_path():
    base = Path(os.environ.get("XDG_STATE_HOME", ""))
    if not base.is_absolute():
        base = Path.home() / ".local/state"
    return base / "chatgpt-browser" / "idle.sqlite3"


def connect(path):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = path.parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("Browser reminder state directory must be private and owned by you")
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("Browser reminder state file must be private and owned by you")
    finally:
        os.close(fd)
    db = sqlite3.connect(path, timeout=0.5)
    db.execute("""CREATE TABLE IF NOT EXISTS calls (
        session TEXT, turn TEXT, call TEXT, finished REAL, expires REAL,
        PRIMARY KEY (session, turn, call))""")
    return db


def identity(event, name):
    value = event.get(name)
    if not isinstance(value, str) or not value.strip() or len(value) > 512 or "\0" in value:
        raise ValueError(f"Missing or invalid {name}")
    return value


def update(db, event):
    """Register synchronously, so delayed background completions cannot resurrect a turn."""
    session = identity(event, "session_id")
    kind = identity(event, "hook_event_name")
    turn = None if kind == "SessionEnd" else identity(event, "turn_id")
    with db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM calls WHERE expires < ?", (time.time(),))
        if kind == "SessionEnd":
            db.execute("DELETE FROM calls WHERE session = ?", (session,))
        elif kind in {"Stop", "Interrupt"} or event.get("tool_name") == "mcp__node_repl__js_reset":
            db.execute("DELETE FROM calls WHERE session = ? AND turn = ?", (session, turn))
        elif kind == "PreToolUse":
            call = identity(event, "tool_use_id")
            first = not db.execute("SELECT 1 FROM calls WHERE session = ? AND turn = ?",
                                   (session, turn)).fetchone()
            db.execute("DELETE FROM calls WHERE session = ? AND turn = ? AND finished IS NOT NULL",
                       (session, turn))
            db.execute("INSERT OR IGNORE INTO calls VALUES (?, ?, ?, NULL, ?)",
                       (session, turn, call, time.time() + 86400))
            if first:
                return f"Browser work: follow {GUIDE} for window reuse, visible task groups, tab preservation and task-scoped release."
        elif kind == "PostToolUse":
            call = identity(event, "tool_use_id")
            changed = db.execute("""UPDATE calls SET finished = ?
                WHERE session = ? AND turn = ? AND call = ? AND finished IS NULL""",
                (time.monotonic(), session, turn, call)).rowcount
            if changed:
                return (session, turn, call)
    return None


def remaining(db, key, idle_seconds):
    """Atomically claim the reminder; a new call or a turn ending cancels the old timer."""
    session, turn, call = key
    with db:
        db.execute("BEGIN IMMEDIATE")
        rows = db.execute("""SELECT call, finished FROM calls WHERE session = ? AND turn = ?
            ORDER BY finished DESC, rowid DESC""", (session, turn)).fetchall()
        if not rows or rows[0][0] != call or any(row[1] is None for row in rows):
            return None
        seconds = rows[0][1] + idle_seconds - time.monotonic()
        if seconds <= 0:
            db.execute("DELETE FROM calls WHERE session = ? AND turn = ?", (session, turn))
        return max(0, seconds)


def run(event, path, idle_seconds=IDLE_SECONDS):
    kind = event.get("hook_event_name")
    if kind not in {"PreToolUse", "PostToolUse", "Stop", "Interrupt", "SessionEnd"}:
        return None
    if kind in {"PreToolUse", "PostToolUse"} and event.get("tool_name") not in TOOLS:
        return None
    if kind != "PreToolUse" and not path.exists():
        return None
    db = connect(path)
    try:
        result = update(db, event)
        if isinstance(result, tuple):
            while (seconds := remaining(db, result, idle_seconds)) is not None:
                if seconds == 0:
                    return ("Browser-capable JavaScript tool has been idle for five minutes. "
                            "Review control held by this task: keep it for ongoing work or a pending handoff; "
                            "otherwise preserve needed tabs, restore borrowed grouping and release through "
                            f"supported task-scoped controls. Follow {GUIDE}; leave shared MCP services intact.")
                time.sleep(min(seconds, 1))
        elif isinstance(result, str):
            return result
    finally:
        db.close()
    return None


def main():
    os.umask(0o077)
    try:
        event = json.load(sys.stdin)
        if not isinstance(event, dict):
            raise ValueError("Expected a hook event object")
        message = run(event, state_path())
        if message:
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": event["hook_event_name"], "additionalContext": message}}))
    except (ValueError, OSError, sqlite3.Error):
        print("Browser idle reminder unavailable; browser cleanup guidance still applies.", file=sys.stderr)


if __name__ == "__main__":
    main()

"""Best-effort caller metadata, joined by exact session identity, never global defaults."""

import os
import re
import sqlite3
import stat
import tomllib
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from .models import decode_json, text

SESSION = re.compile(r"[A-Za-z0-9_-]{1,200}\Z")
KEYS = {"codex": "threadId", "claude": "sessionId", "agy": "conversationId", "opencode": "sessionId"}


@dataclass(frozen=True)
class Context:
    harness: str | None = None
    session: str | None = None
    model: str | None = None
    effort: str | None = None


def native_bytes(path: Path, *, tail: bool = False) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError("unsafe native metadata")
        limit = 4 * 1024**2 if tail else 65536
        if info.st_size > limit:
            if not tail:
                raise ValueError("oversized native metadata")
            os.lseek(fd, -limit, os.SEEK_END)
        raw = os.read(fd, limit + 1)
        if len(raw) > limit:
            raise ValueError("native metadata changed while reading")
        return raw.split(b"\n", 1)[-1] if tail and info.st_size > limit else raw
    finally:
        os.close(fd)


def native_object(path: Path) -> dict:
    value = decode_json(native_bytes(path).decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("native metadata must be an object")
    return value


def bridge() -> Context:
    # A worker may inherit its coordinator's native environment: its own job wins.
    name = os.environ.get("AGENT_BRIDGE_JOB", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]+/[A-Za-z0-9_-]+", name):
        return Context()
    home = Path(os.environ.get("AGENT_BRIDGE_HOME") or "~/.local/state/agent-bridge").expanduser()
    if not home.is_absolute():
        return Context()
    root = home.resolve() / "jobs"
    path = root / name / "state.json"
    if path.resolve() != path:
        return Context()
    data = native_object(path)
    harness = data.get("backend")
    if not isinstance(harness, str) or harness not in KEYS:
        return Context()
    return Context(
        harness,
        text(data.get(KEYS[harness]), 200, nullable=True),
        text(data.get("model"), 128, nullable=True),
        text(data.get("effort"), 32, nullable=True),
    )


def claude_session(home: Path, proc_root: Path = Path("/proc")) -> str | None:
    known = os.environ.get("CLAUDE_CODE_SESSION_ID")
    if known:
        return known
    pid, seen = os.getppid(), set()
    for _ in range(32):
        if pid <= 1 or pid in seen:
            break
        seen.add(pid)
        process = proc_root / str(pid)
        try:
            if process.joinpath("comm").read_text().strip() == "claude":
                data = native_object(home / "sessions" / f"{pid}.json")
                if type(data.get("pid")) is int and data["pid"] == pid:
                    return text(data.get("sessionId"), 200, nullable=True)
            pid = int(process.joinpath("stat").read_text().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError):
            break
    return None


def codex_details(session: str) -> tuple[str | None, str | None]:
    home = Path(os.environ.get("CODEX_HOME") or "~/.codex").expanduser()
    sqlite_home = home
    config = home / "config.toml"
    if config.exists():
        setting = tomllib.loads(native_bytes(config).decode("utf-8")).get("sqlite_home")
        if setting is not None:
            if not isinstance(setting, str) or not Path(setting).is_absolute():
                return None, None
            sqlite_home = Path(setting)
    # Native schema adapter, not an API guarantee; absent/changed schemas remain unknown.
    path = sqlite_home / "state_5.sqlite"
    if not path.is_absolute() or path.is_symlink():
        return None, None
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=0.1)) as db:
        row = db.execute("SELECT model, reasoning_effort FROM threads WHERE id = ?", (session,)).fetchone()
    if row is None:
        return None, None
    return text(row[0], 128, nullable=True), text(row[1], 32, nullable=True)


def claude_model(session: str) -> str | None:
    home = Path(os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude").expanduser()
    paths = list((home / "projects").glob(f"*/{session}.jsonl"))
    if len(paths) != 1:
        return None
    for line in reversed(native_bytes(paths[0], tail=True).splitlines()):
        try:
            value = decode_json(line.decode("utf-8"))
        except (ValueError, UnicodeError):
            continue
        if not isinstance(value, dict) or value.get("sessionId") != session:
            continue
        if value.get("type") == "assistant" and not value.get("isSidechain"):
            message = value.get("message")
            if isinstance(message, dict) and message.get("model") not in (None, "<synthetic>"):
                return text(message["model"], 128)
    return None


def infer() -> Context:
    result = Context()
    try:
        if os.environ.get("AGENT_BRIDGE_WORKER") == "1":
            result = bridge()
        elif os.environ.get("CLAUDECODE") == "1":
            home = Path(os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude").expanduser()
            result = Context("claude", claude_session(home))
        elif os.environ.get("ANTIGRAVITY_CONVERSATION_ID"):
            result = Context("agy", os.environ["ANTIGRAVITY_CONVERSATION_ID"])
        elif os.environ.get("CODEX_THREAD_ID"):
            result = Context("codex", os.environ["CODEX_THREAD_ID"])
        elif os.environ.get("AGENT_BRIDGE_ROOT_HARNESS") in KEYS:
            result = Context(
                os.environ["AGENT_BRIDGE_ROOT_HARNESS"], os.environ.get("AGENT_BRIDGE_ROOT_SESSION")
            )
        if result.session is None or not SESSION.fullmatch(result.session):
            return Context(result.harness)
        if result.harness == "codex":
            model, effort = codex_details(result.session)
            return Context(result.harness, result.session, model or result.model, effort or result.effort)
        if result.harness == "claude":
            return Context(
                result.harness, result.session, claude_model(result.session) or result.model, result.effort
            )
    except (OSError, ValueError, sqlite3.Error):
        pass  # Optional native metadata must not block work or expose private diagnostics.
    return result

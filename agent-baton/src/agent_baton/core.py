import fcntl
import json
import os
import secrets
import time
import tomllib
from contextlib import contextmanager
from pathlib import Path

STATE = Path(os.environ.get("AGENT_BATON_HOME", "~/.local/state/agent-baton")).expanduser()
CONFIG = Path(os.environ.get("AGENT_BATON_CONFIG", "~/.config/agent-baton/config.toml")).expanduser()
BATONS = STATE / "batons"
KEEP_RESOLVED_S = 86400
SESSION_KEYS = (  # an explicit id wins; the harness ids are each conversation's own
    ("AGENT_BATON_SESSION", "explicit"),
    ("CODEX_THREAD_ID", "codex"),
    ("CLAUDE_CODE_SESSION_ID", "claude"),
)
DEFAULTS = {
    "ttl": 600,  # seconds the human has before the baton expires
    "port": 0,  # fixed port for the human page; needed when `url` points at a proxy such as tailscale serve
    "slots": 1,  # phone ports in use: baton k listens on port+k and is reached at the url's port+k
    "url": "",  # public base URL of the human page, for phone links
    "ntfy": "",  # ntfy topic URL for phone notifications
    "deny": [  # never browse these, baton or not; the config list adds to these
        "chrome://password-manager",
        "chrome://settings/passwords",
        "chrome://settings/payments",
        "1password.com",
        "bitwarden.com",
        "lastpass.com",
        "dashlane.com",
    ],
    "no_type": [  # `type` refuses windows whose title contains any of these (terminals, agent UIs)
        "terminal",
        "powershell",
        "command prompt",
        "cmd.exe",
        "ghostty",
        "claude code",
        "codex",
    ],
    "browser_tools": r"(?i)^mcp__.*(browser|chrome|computer|playwright|puppeteer|cua|devtools)",
    "browser_commands": r"(?i)\b(cua-driver|playwright|puppeteer|agent-browser|chrome-devtools)\b",
}


def config():
    user = tomllib.loads(CONFIG.read_text(encoding="utf-8")) if CONFIG.is_file() else {}
    merged = {**DEFAULTS, **user}
    merged["deny"] = [*DEFAULTS["deny"], *user.get("deny", [])]
    return merged


def now():
    return int(time.time())


def session():
    """A conversation owner, never a shared harness name, working directory or terminal."""
    for key, namespace in SESSION_KEYS:
        value = os.environ.get(key)
        if value is not None:
            if not value or value != value.strip() or len(value) > 200 or any(c.isspace() for c in value):
                raise ValueError(
                    f"{key} must be a nonempty session id without whitespace (max 200 characters)"
                )
            return f"{namespace}:{value}"
    raise ValueError(
        "no session identity: set AGENT_BATON_SESSION to a unique conversation id on every Baton call; "
        "reuse it only in this conversation (Codex and Claude Code supply their own automatically)"
    )


def path_of(baton_id):
    return BATONS / f"{baton_id}.json"


def save(baton):
    BATONS.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = path_of(baton["id"])
    tmp = path.with_name(f".{path.stem}.{secrets.token_hex(4)}.tmp")  # page threads and the loop both save
    tmp.touch(mode=0o600, exist_ok=False)
    tmp.write_text(json.dumps(baton, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


@contextmanager
def locked(baton_id):
    """Serialize read-modify-write of one baton across the daemon and every CLI process."""
    lock_path = BATONS / f"{baton_id}.lock"
    lock_path.touch(mode=0o600, exist_ok=True)
    with lock_path.open() as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def read(baton_id):
    return json.loads(path_of(baton_id).read_text(encoding="utf-8"))


def expire(baton):
    """Mark a lapsed held baton expired; the caller holds its lock."""
    if baton["status"] == "held" and baton["expires"] <= now():
        baton["status"] = "expired"
        save(baton)
    return baton


def settle(baton):
    """Expiry is judged at read time, so a dead daemon can never keep the agent blind.

    A late answer may have landed since this copy was read, so the verdict is taken from the file."""
    if baton["status"] == "held" and baton["expires"] <= now():
        with locked(baton["id"]):
            return expire(read(baton["id"]))
    return baton


def load(baton_id):
    return settle(read(baton_id))


def all_batons(*, all_sessions=False):
    owner = None if all_sessions else session()
    out = []
    for path in sorted(BATONS.glob("*.json")) if BATONS.is_dir() else []:
        try:
            baton = json.loads(path.read_text(encoding="utf-8"))
            if all_sessions or baton.get("session") == owner:
                out.append(settle(baton))
        except (OSError, ValueError, KeyError):
            continue  # a half-written or foreign file must never break the guard
    return sorted(out, key=lambda b: b["created"])


def held(kind=None, *, all_sessions=False):
    """Open batons, optionally filtered by kind (login, run, ask or question)."""
    return [
        b
        for b in all_batons(all_sessions=all_sessions)
        if b["status"] == "held" and kind in (None, b["kind"])
    ]


def create(site, reason, by, ttl, kind="login", **extra):
    owner = session()
    BATONS.mkdir(parents=True, exist_ok=True, mode=0o700)
    while True:
        baton_id = secrets.token_hex(8)
        try:
            path_of(baton_id).touch(mode=0o600, exist_ok=False)
            break
        except FileExistsError:
            continue  # never overwrite another request, even if a random id collides
    baton = {
        "kind": kind,
        "site": site,
        "reason": reason,
        "by": by,
        "created": now(),
        "expires": now() + ttl,
        "status": "held",
        **extra,
        "id": baton_id,
        "session": owner,
    }
    try:
        save(baton)
    except BaseException:
        path_of(baton_id).unlink(missing_ok=True)
        raise
    return baton


def output_path(baton_id, stream):
    return BATONS / f"{baton_id}.{stream}"


def sweep():
    for baton in all_batons(all_sessions=True):
        if baton["status"] != "held" and now() - baton["expires"] > KEEP_RESOLVED_S:
            for path in (
                path_of(baton["id"]),
                output_path(baton["id"], "out"),
                output_path(baton["id"], "err"),
                BATONS / f"{baton['id']}.lock",
            ):
                path.unlink(missing_ok=True)


def resolve(baton_id, status):
    with locked(baton_id):
        baton = expire(read(baton_id))
        if baton["status"] == "held":
            baton["status"] = status
            save(baton)
    return baton


def left(baton):
    minutes = max(0, baton["expires"] - now()) / 60
    return f"{minutes:.0f} min" if minutes >= 1 else f"{max(0, baton['expires'] - now())} s"

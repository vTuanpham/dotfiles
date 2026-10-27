import fcntl
import json
import os
import re
import shutil
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from . import retries

POLL = 0.2
URGENT_KINDS = {
    "question",
    "question_timeout",
    "approval_declined",
    "turn_completed",
    "error",
    "permission_denied",
    "peer_unknown",
    "steer_queued",
}
HOME = Path(os.environ.get("AGENT_BRIDGE_HOME", "~/.local/state/agent-bridge")).expanduser()
JOBS = HOME / "jobs"
ARCHIVE = HOME / "archive.jsonl"
MESSAGING_RULE = (
    "You work for a coordinator who reads your messages live. Every message you write is logged. "
    "Default messages are INFO: the coordinator reads them whenever convenient, so keep them few "
    "(checkpoints like 'edits done + check results', not step narration). Start a message with "
    "'URGENT:' only when the coordinator must act now: you are blocked, you need a decision that is "
    "theirs, you found a safety/data-loss risk, or you are about to do something irreversible. "
    "After an URGENT message keep working on anything unblocked. Your final message is the report. "
    "agent-bridge peers lists your sibling workers. "
    "Peer messaging needs no tool: to reach another worker (names come from your brief), just write "
    "an ordinary message to the coordinator whose text starts with 'TO <peer-name>: ' "
    "(comma-separate several names). Plain messages already reach the coordinator, so never address "
    "it with 'TO'. The runner delivers it into that peer's live turn. Use it for "
    "concrete cross-area requests or hand-offs, not chatter; replies arrive as '[from <name>] ...'. "
    "Coordinator steers may arrive mid-turn as user messages; follow them. You are a delegated worker "
    "and must never start agent-bridge jobs, subagents, or other agents yourself. "
    "Use agent-bridge heavy --mem SIZE -- <command> only for model inference or benchmarks, dataset "
    "downloads/extraction, full test suites, long-lived local servers or headless browsers, and commands "
    "expected to use more than about 1 GiB or several cores for over a minute. "
    "Do not wrap worker runners, git, edits, reads, lint, type checks or targeted tests; "
    "everything else runs directly. "
    "Wrap the whole heavy foreground job; do not nest heavy calls or background a server outside its slot. "
    "Declare expected peak memory with --mem (for example 1G or 2500M); use --exclusive only for timing "
    "measurements, never for test suites. Fitting heavy jobs run concurrently. "
    "Waiting for a heavy slot is normal and is never a blocker to report. Do not send queue progress "
    "messages; report only a holder shown dead or a wait exceeding 30 minutes excluding root pauses. "
    "A root pause is normal; wait for resume. Queue cancellation exits 125; follow the root's steer. "
    "Before a long silent build, benchmark, peer or external wait, use agent-bridge waiting "
    "--on command|peer|root|external|dependency --for 20m --note 'short reason'; "
    "add --peer NAME for a sibling. Your next tool call or message clears it."
)
REDELIVERED = "(redelivered after a runner restart; skip it if you already handled it)"


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def append(path, value):
    with Path(path).open("a", encoding="utf-8") as f:
        f.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")


def save(path, state):
    path = Path(path)
    if path.name != "state.json":
        return atomic_save(path, state)
    # A runner's in-memory state must neither erase nor revive a worker declaration.
    with state_lock(path.parent):
        payload = dict(state)
        current = load_state(path.parent) if path.exists() else {}
        for key in ("waiting", "assessment_notices"):
            if key in current:
                payload[key] = current[key]
            else:
                payload.pop(key, None)
        atomic_save(path, payload)


@contextmanager
def state_lock(job):
    fd = os.open(Path(job) / "state.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def atomic_save(path, state):
    path = Path(path)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def resolve_job(value):
    path = Path(value).expanduser()
    if path.is_absolute():
        resolved = path.resolve()
    else:
        parts = path.parts
        if len(parts) != 2 or any(p in (".", "..") for p in parts):
            raise ValueError("relative job must be exactly <owner>/<name>")
        resolved = (JOBS / path).resolve()
    jobs_root = JOBS.resolve()
    if resolved == jobs_root or not resolved.is_relative_to(jobs_root):
        raise ValueError("job must be under the agent-bridge jobs directory")
    return resolved


def lock_runner(job):
    fd = os.open(Path(job) / "runner.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise RuntimeError("job already has a runner")
    return fd


@contextmanager
def steer_lock(job):
    # Enqueue and the runner's final queue check must share one handoff boundary.
    with (Path(job) / "steer.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def load_state(job):
    state = json.loads((Path(job) / "state.json").read_text(encoding="utf-8"))
    if not isinstance(state, dict):
        raise ValueError("job state must be a JSON object")
    return state


def log(job, kind, level=None, **fields):
    if kind in {"command_start", "message", "turn_started", "turn_completed", "turn_failed",
                "error", "question", "approval_declined", "permission_denied", "question_timeout"}:
        from .waiting import clear

        try:
            clear(Path(job))
        except (OSError, ValueError):
            pass  # state damage must never prevent a native failure/message reaching the log
    if kind == "message" and isinstance(fields.get("text"), str):
        head, sep, _ = fields["text"].partition(":")
        if sep and head.upper().startswith("TO "):
            recipients = [n.strip().lower() for n in head[3:].split(",")]
            if not any(n in {"root", "coordinator", Path(job).parent.name.lower()} for n in recipients):
                fields["peerDirected"] = True
    event = {"at": stamp(), "kind": kind,
             "level": level or ("urgent" if kind in URGENT_KINDS else "info"), **fields}
    attempt = retries.ATTEMPT.get()
    if attempt is not None and kind in {"error", "turn_failed", "turn_completed"}:
        attempt.append(event)
        if retries.failed(event):
            event = {**event, "kind": "attempt_failed", "level": "info", "originalKind": kind}
    append(
        Path(job) / "live.jsonl",
        event,
    )


def make_steer(job, text):
    folder = Path(job).resolve() / "steer"
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / f".{uuid.uuid4().hex}.tmp"
    tmp.write_text(text.strip() + "\n", encoding="utf-8")
    try:
        while True:
            nums = [int(p.stem) for p in folder.glob("*.md") if p.stem.isdecimal()]
            sent = folder / "sent"
            if sent.exists():
                nums.extend(int(p.stem) for p in sent.glob("*.md") if p.stem.isdecimal())
            path = folder / f"{max(nums, default=0) + 1:03d}.md"
            try:
                os.link(tmp, path)
                return path
            except FileExistsError:
                continue
    finally:
        tmp.unlink(missing_ok=True)


def route_to_peers(job, text):
    head, sep, body = text.partition(":")
    if not sep or not head.upper().startswith("TO "):
        return
    job = Path(job)
    job = job.resolve()
    for name in (n.strip() for n in head[3:].split(",")):
        if name.lower() in ("root", "coordinator") or name == job.parent.name:
            continue  # The coordinator already reads every message; not an unknown peer.
        peer = job.parent / name
        valid_name = name not in ("", ".", "..") and "/" not in name and "\\" not in name
        try:
            sibling = peer.resolve().parent == job.parent
        except (OSError, RuntimeError):
            sibling = False
        try:
            available = (valid_name and name != job.name and sibling and (peer / "state.json").is_file()
                         and not load_state(peer).get("retiredAt"))
        except (OSError, ValueError):
            available = False
        if available:
            make_steer(peer, f"[from {job.name}] {body.strip()}")
            from .peers import fields

            log(job, "peer_sent", **fields(job, name, body.strip()))
        else:
            log(job, "peer_unknown", level="urgent", to=name)


def tree_size(path):
    """Bytes under path; symlinks count as links, never followed."""
    total = 0
    for entry in os.scandir(path):
        total += entry.stat(follow_symlinks=False).st_size
        if entry.is_dir(follow_symlinks=False):
            total += tree_size(entry.path)
    return total


def human(size):
    for unit in "BKMG":
        if size < 1024:
            return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}T"


WORKER_FLAG = "AGENT_BRIDGE_WORKER"
SECRET_ENV = re.compile("KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTH|COOKIE", re.IGNORECASE)


def link(target, path):
    """Symlink path to target unless something, even a dangling link, is already there."""
    if not os.path.lexists(path):
        Path(path).symlink_to(target)


def command_env(**extra):
    """One environment boundary for workers and subprocesses; explicit denial wins over opt-in."""
    policy = {}
    for name in ("AGENT_BRIDGE_PASS_ENV", "AGENT_BRIDGE_DENY_ENV"):
        value = os.environ.get(name, "")
        names = {part.strip() for part in value.split(",")} if value else set()
        if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", entry) for entry in names):
            raise ValueError(f"{name} must contain comma-separated environment variable names")
        policy[name] = names
    passed, denied = policy["AGENT_BRIDGE_PASS_ENV"], policy["AGENT_BRIDGE_DENY_ENV"]
    return {name: value for name, value in {**os.environ, **extra}.items()
            if name not in denied and (name in passed or not SECRET_ENV.search(name))}


def worker_env(job=None, **extra):
    """Filtered backend environment plus the bridge worker identity and CLI restrictions."""
    return {
        **command_env(**extra),
        "AGENT_BRIDGE_HOST_PID_NAMESPACE": os.readlink("/proc/self/ns/pid"),
        WORKER_FLAG: "1",
        **({"AGENT_BRIDGE_JOB": f"{Path(job).parent.name}/{Path(job).name}"} if job else {}),
    }


def job_caps(state=None):
    state = state or {}
    return {"memoryMax": state.get("memoryMax") or os.environ.get("CODEX_JOB_MEMORY_MAX", "2500M"),
            "cpuQuota": state.get("cpuQuota") or os.environ.get("CODEX_JOB_CPU_QUOTA", "300%")}


def capped(cmd, state=None):
    if not shutil.which("systemd-run"):
        return cmd
    caps = job_caps(state)
    return [
        "systemd-run",
        "--user",
        "--scope",
        "--quiet",
        "--slice=codex.slice",
        "-p",
        f"MemoryMax={caps['memoryMax']}",
        "-p",
        "MemorySwapMax=512M",
        "-p",
        f"CPUQuota={caps['cpuQuota']}",
        "nice",
        "-n",
        "10",
        *cmd,
    ]


def runner_started(state, path):
    state["runnerPid"] = os.getpid()
    save(path, state)


def runner_finished(state, path):
    current = load_state(Path(path).parent)
    if current.get("runnerPid") == os.getpid():
        state.pop("runnerPid", None)
        save(path, state)


def poll_steers(job, send, known=None, state=None, defer=False, redeliver=False, turn_key=None):
    folder = Path(job) / "steer"
    folder.mkdir(parents=True, exist_ok=True)
    sent = folder / "sent"
    sent.mkdir(exist_ok=True)
    inflight = state.get("inflight") if defer and state is not None else None
    if inflight:
        path = folder / inflight["file"]
        if not path.exists() and (sent / path.name).exists():
            confirm_steer(job, state)
            return False
        if not redeliver:
            return False
        text = path.read_text(encoding="utf-8").strip()
        if turn_key:
            inflight[turn_key] = state.get(turn_key, 0) + 1
            save(Path(job) / "state.json", state)
        send(f"{REDELIVERED}\n{text}")
        log(job, "steer_redelivered", file=path.name)
        return True
    for path in sorted(folder.glob("*.md")):
        if path.stem.isdecimal() and (text := path.read_text(encoding="utf-8").strip()):
            cid = f"steer-{path.stem}"
            if known is not None and f"steer-{path.stem}" in known:
                os.replace(path, sent / path.name)
                continue
            if state is not None:
                state["inflight"] = {"id": cid, "file": path.name}
                if turn_key:
                    state["inflight"][turn_key] = state.get(turn_key, 0) + 1
                save(Path(job) / "state.json", state)
            if defer:
                send(text)
            elif state is not None:
                send(text, cid)
            else:
                send(text)
            if defer:
                return True
            os.replace(path, sent / path.name)
            if state is not None:
                state["inflight"] = None
                save(Path(job) / "state.json", state)
            log(job, "steer_sent", file=path.name)
            return True
    return False


def confirm_steer(job, state):
    inflight = state.get("inflight")
    if not inflight:
        return
    path = Path(job) / "steer" / inflight["file"]
    sent = path.parent / "sent"
    sent.mkdir(exist_ok=True)
    if path.exists():
        os.replace(path, sent / path.name)
    state["inflight"] = None
    save(Path(job) / "state.json", state)
    log(job, "steer_sent", file=inflight["file"])

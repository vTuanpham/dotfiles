import fcntl
import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

POLL = 0.2
URGENT_KINDS = {
    "question",
    "question_timeout",
    "approval_declined",
    "turn_completed",
    "error",
    "permission_denied",
    "peer_unknown",
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
    "and must never start agent-bridge jobs, subagents, or other agents yourself."
)
REDELIVERED = "(redelivered after a runner restart; skip it if you already handled it)"


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def append(path, value):
    with Path(path).open("a", encoding="utf-8") as f:
        f.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")


def save(path, state):
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


def load_state(job):
    return json.loads((Path(job) / "state.json").read_text(encoding="utf-8"))


def log(job, kind, level=None, **fields):
    append(
        Path(job) / "live.jsonl",
        {
            "at": stamp(),
            "kind": kind,
            "level": level or ("urgent" if kind in URGENT_KINDS else "info"),
            **fields,
        },
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
        if valid_name and name != job.name and sibling and (peer / "state.json").is_file():
            make_steer(peer, f"[from {job.name}] {body.strip()}")
            log(job, "peer_sent", to=name)
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


def link(target, path):
    """Symlink path to target unless something, even a dangling link, is already there."""
    if not os.path.lexists(path):
        Path(path).symlink_to(target)


def worker_env(job=None, **extra):
    """Environment for a backend process: everything it runs is a delegated worker, which the CLI refuses."""
    return {
        **os.environ,
        WORKER_FLAG: "1",
        **({"AGENT_BRIDGE_JOB": f"{Path(job).parent.name}/{Path(job).name}"} if job else {}),
        **extra,
    }


def capped(cmd):
    if not shutil.which("systemd-run"):
        return cmd
    mem, cpu = os.environ.get("CODEX_JOB_MEMORY_MAX", "2500M"), os.environ.get("CODEX_JOB_CPU_QUOTA", "300%")
    return [
        "systemd-run",
        "--user",
        "--scope",
        "--quiet",
        "--slice=codex.slice",
        "-p",
        f"MemoryMax={mem}",
        "-p",
        "MemorySwapMax=512M",
        "-p",
        f"CPUQuota={cpu}",
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

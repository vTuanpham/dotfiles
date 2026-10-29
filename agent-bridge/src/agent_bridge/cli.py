import argparse
import json
import os
import sys
import time
from contextlib import ExitStack
from pathlib import Path

from . import (
    agy,
    claude,
    codex,
    groups,
    heavy,
    heavy_control,
    opencode,
    owner_binding,
    reference,
    refresh,
    resources,
    retirement,
    retries,
    status,
    status_render,
    waiting,
)
from .acknowledgements import acknowledge, event_lines
from .assessment import DEFAULT_DECLARED_WAIT_SECONDS, SILENCE_SECONDS
from .core import (
    ARCHIVE,
    JOBS,
    POLL,
    WORKER_FLAG,
    job_caps,
    load_state,
    lock_runner,
    log,
    make_steer,
    resolve_job,
    runner_finished,
    save,
    stamp,
    steer_lock,
)
from .watch import watch

BACKENDS = {"codex": codex, "agy": agy, "claude": claude, "opencode": opencode}
ROOT_COMMANDS = {"start", "resume", "steer", "interrupt", "stop"}


def watch_seconds(value):
    try:
        return int(value)
    except ValueError:
        short = value[:24] + ("…" if len(value) > 24 else "")
        raise argparse.ArgumentTypeError(
            f"invalid --watch value {short!r}; put text before --watch, use --watch=SECONDS, "
            "or use --prompt-file"
        ) from None


WATCH = {
    "nargs": "?",
    "const": 1800,
    "type": watch_seconds,
    "metavar": "SECONDS",
    "help": (
        "run detached and wait for the first urgent event (default: 1800s); a Codex watch may "
        "continue past that timeout while a reminder is scheduled"
    ),
}


def harness():
    if os.environ.get("CLAUDECODE") == "1":
        return "claude"
    if os.environ.get("CODEX_THREAD_ID"):
        return "codex"
    return "unknown"


def record_root(job):
    owner = Path(job).parent
    owner_binding.record(owner, root_identity())


def root_identity():
    return owner_binding.identity()


def session_bindings():
    """Export identity metadata only, never prompts, credentials or account settings."""
    result = []
    if not JOBS.is_dir():
        return {"version": 1, "sessions": result}
    keys = {"codex": "threadId", "claude": "sessionId", "opencode": "sessionId", "agy": "conversationId"}
    for path in sorted(JOBS.glob("*/*/state.json")):
        try:
            if (path.is_symlink() or not path.resolve().is_relative_to(JOBS.resolve())
                    or path.stat().st_size > 1048576):
                continue
            state = load_state(path.parent)
            if state.get("retiredAt"):
                continue
            backend = state.get("backend")
            identifier = state.get(keys.get(backend))
            title = state.get("title", "")
            parent = state.get("parent")
            if (backend not in keys or type(identifier) is not str or not identifier or len(identifier) > 200
                    or type(title) is not str or len(title) > 1000):
                continue
            if parent is not None and (type(parent) is not dict or set(parent) != {"backend", "session_id"}
                    or parent["backend"] not in keys or type(parent["session_id"]) is not str
                    or not parent["session_id"] or len(parent["session_id"]) > 200):
                parent = None
            result.append({"backend": backend, "session_id": identifier,
                           "job": path.parent.parent.name + "/" + path.parent.name,
                           "title": title, "parent": parent})
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    return {"version": 1, "sessions": result}


def events(job, offset=0):
    return [event for _, event in event_lines(Path(job), offset)]


def unanswered_urgent(job):
    from .status_inputs import unanswered

    return unanswered(Path(job), events(job))


def linger(job, state, state_path, backend):
    if state.get("autoAnswers", 0) >= 2 or not unanswered_urgent(job):
        return
    wait = max(0, int(os.environ.get("AGENT_BRIDGE_ROOT_WAIT", "20"))) * 60
    deadline = time.monotonic() + wait
    state["runnerPid"] = os.getpid()
    save(state_path, state)
    log(job, "root_wait", level="info", minutes=int(wait // 60))
    while True:
        if (job / "stop").exists():
            (job / "stop").unlink()
            log(job, "stopped")
            return
        queued = sorted((job / "steer").glob("[0-9]*.md"))
        if queued:
            state = load_state(job)
            state["autoAnswers"] = 0
            save(state_path, state)
            retries.run(job, state, state_path, backend, "", True, {})
            if not unanswered_urgent(job):
                return
            deadline = time.monotonic() + wait
        if time.monotonic() >= deadline:
            state = load_state(job)
            if state.get("autoAnswers", 0) >= 2:
                return
            state["autoAnswers"] = state.get("autoAnswers", 0) + 1
            save(state_path, state)
            make_steer(
                job,
                f"Root is unavailable (no reply in {int(wait // 60)} min). Take the most conservative "
                "reasonable choice for your open question, record it as a decision in your final report, "
                "and continue.",
            )
            log(job, "root_absent", level="urgent", minutes=int(wait // 60), count=state["autoAnswers"])
            retries.run(job, state, state_path, backend, "", True, {})
            if not unanswered_urgent(job):
                return
            deadline = time.monotonic() + wait
        time.sleep(POLL)


def result_text(job, all_messages=False):
    evs = events(job)
    ends = [i for i, e in enumerate(evs) if e.get("kind") == "turn_completed"]
    if ends and any(e.get("kind") == "message" for e in evs[ends[-1] + 1 :]):
        start, end = ends[-1] + 1, len(evs)
    else:
        start = ends[-2] + 1 if len(ends) > 1 else 0
        end = ends[-1] + 1 if ends else len(evs)
    messages = (
        [str(e.get("text", "")) for e in evs if e.get("kind") == "message"]
        if all_messages
        else [str(e.get("text", "")) for e in evs[start:end] if e.get("kind") == "message"]
    )
    return "\n\n".join(text for text in messages if text)


def run_with_linger(
    job, state, state_path, backend, prompt, resume, extra, runner_fd=None, *, root_prompt=False
):
    try:
        while True:
            live_path = job / "live.jsonl"
            before = live_path.stat().st_size if live_path.exists() else 0
            if not retries.run(
                job, state, state_path, backend, prompt, resume, extra, root_prompt=root_prompt
            ):
                return
            if any(e.get("kind") in {"root_steer", "root_prompt"} for e in events(job, before)):
                state["autoAnswers"] = 0
                save(state_path, state)
            if backend is agy:
                agy.fallback(job, state, state_path)
            if not extra.get("compact"):
                linger(job, state, state_path, backend)
            with steer_lock(job):
                stopped = any(e.get("kind") == "stopped" for e in events(job, before))
                if (runner_fd is not None and not extra.get("compact") and not stopped
                        and list((job / "steer").glob("[0-9]*.md"))):
                    state = load_state(job)
                    state["autoAnswers"] = 0
                    save(state_path, state)
                    prompt, resume = "", True
                    root_prompt = False
                    continue
                runner_finished(load_state(job), state_path)
                if runner_fd is not None:
                    os.close(runner_fd)
                    runner_fd = None
                return
    finally:
        if runner_fd is not None:
            with steer_lock(job):
                try:
                    runner_finished(load_state(job), state_path)
                finally:
                    os.close(runner_fd)


def read_prompt(prompt_file):
    """--prompt-file PATH, or '-' for stdin. Stdin is never sniffed: harnesses hand commands an open,
    never-closing pipe, so an implicit read would block forever."""
    text = sys.stdin.read() if prompt_file == "-" else Path(prompt_file).read_text(encoding="utf-8")
    if not text.strip():
        raise RuntimeError(f"empty prompt from {prompt_file}")
    return text.strip()


GUIDES = Path(__file__).with_name("guide")


def guide(*names):
    """Read the maintained workflow, plan reference or backend notes on demand."""
    return "\n\n".join((GUIDES / f"{name}.md").read_text(encoding="utf-8").strip() for name in names)


def main():
    if (
        os.environ.get(WORKER_FLAG)
        and len(sys.argv) > 1
        and not any(flag in sys.argv[1:] for flag in ("-h", "--help"))
        and sys.argv[1] in {"start", "resume", "steer", "interrupt", "stop", "compact", "retire", "handoff",
                            "restore", "purge", "sessions", "ack", "group"}
    ):
        print("agent-bridge: delegated workers can't drive agent-bridge jobs", file=sys.stderr)
        raise SystemExit(2)
    p = argparse.ArgumentParser(
        prog="agent-bridge",
        description="Run delegated jobs; jobs are named <owner>/<name>.",
        epilog=(
            "Workflow: start ... --watch in a background terminal; keep working.\n"
            "Steer delivers to running jobs and resumes idle jobs; --queue only queues.\n"
            "Read result, verify the work, then retire when its context is no longer needed.\n\n"
            "Details: <command> --help for flags; start --help for backend notes.\n"
            "Guides: guide workflow (routing, watch, briefs, review, Keeping the reference current);\n"
            "        guide plans (model strength and costs); guide prints workflow and plans.\n"
            "        guide subscriptions (all tiers; read only for plan-dependent choices).\n"
            "Storage: ~/.local/state/agent-bridge/jobs (or $AGENT_BRIDGE_HOME/jobs)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="command", required=True, metavar="COMMAND")
    g = sub.add_parser("guide", help="read workflow, model, subscription, source or status guidance")
    g.add_argument("topic", nargs="?",
                   choices=("workflow", "plans", "subscriptions", "sources", "heavy", "status"),
                   help="omit to read workflow and plans")
    sub.add_parser(
        "sessions", help="export native job identities as JSON (no transcripts)",
        description="Export native job identities across owners as JSON (no transcript data).",
    )
    snapshot = sub.add_parser("status", help="versioned harness-neutral status snapshot")
    snapshot.add_argument("owner", nargs="*", help="optional owner or owner/job filters")
    snapshot.add_argument("--json", action="store_true", help="emit the version 1 JSON contract")
    snapshot.add_argument("--storage", action="store_true", help="scan sizes and expired retirement safety")
    snapshot.add_argument("--no-quotas", action="store_true",
                          help="skip account caches for a bounded status probe")
    wait = sub.add_parser("waiting", help="declare a bounded silent wait for this worker")
    action = wait.add_mutually_exclusive_group(required=True)
    action.add_argument("--on", choices=waiting.KINDS)
    action.add_argument("--clear", action="store_true")
    wait.add_argument("--for", dest="duration", type=groups.duration,
                      default=DEFAULT_DECLARED_WAIT_SECONDS, help="expected duration, at most 2h")
    wait.add_argument("--note", default="", help="short reason, at most 80 printable characters")
    wait.add_argument("--peer", help="sibling job name for a peer/dependency wait")
    s = sub.add_parser(
        "start",
        help="create a job and run its first turn",
        epilog=(guide("codex", "agy", "claude", "opencode")
                if len(sys.argv) > 1 and sys.argv[1] == "start"
                and any(flag in sys.argv[2:] for flag in ("-h", "--help")) else None),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    s.add_argument("job", help="job as <owner>/<name>")
    s.add_argument("--backend", choices=BACKENDS, required=True, help="worker harness to run")
    s.add_argument(
        "--title", required=True, help="3-48 characters on one line; cannot be only the backend name"
    )
    s.add_argument("--cwd", required=True, help="worker working directory")
    s.add_argument(
        "--sandbox",
        choices=("read-only", "workspace-write"),
        required=True,
        help=(
            "read-only restricts writes and commands per backend; workspace-write permits writes in cwd and "
            "writable roots; "
            "network access depends on the backend"
        ),
    )
    s.add_argument("--model", help="backend model ID")
    s.add_argument("--effort", help="backend reasoning effort or variant")
    s.add_argument("--memory", help="per-job scope cap, such as 4G; default CODEX_JOB_MEMORY_MAX or 2500M")
    s.add_argument("--cpu", help="per-job scope cap, such as 400%%; defaults to CODEX_JOB_CPU_QUOTA or 300%%")
    s.add_argument(
        "--writable-root", action="append", help="extra writable directory; workspace-write only, repeatable"
    )
    s.add_argument(
        "--config",
        action="append",
        help=(
            "Codex override key=value; values parse as JSON when possible "
            '(e.g. web_search="live"); repeatable'
        ),
    )
    s.add_argument("--account", help="agy account name")
    s.add_argument(
        "--allow",
        action="append",
        help="agy permission rule, e.g. 'read_url(*)' for network or 'command(gh)'; repeatable",
    )
    s.add_argument("--deny", action="append", help="agy permission rule; deny takes precedence; repeatable")
    s.add_argument("--prompt-file", help="read prompt from PATH or '-' for stdin; default is <job>/prompt.md")
    s.add_argument("--detach", action="store_true", help="run in the background and return the job path")
    s.add_argument("--watch", **WATCH)
    s.add_argument("--group", type=groups.name, help="root-owned completion wake group")
    r = sub.add_parser("resume", help="continue the same job/session; queued steers take precedence")
    r.add_argument("job", help="job as <owner>/<name>")
    r.add_argument("--model", help="switch model starting on the next turn")
    r.add_argument("--effort", help="switch effort or variant starting on the next turn")
    r.add_argument("--memory", help="memory cap for the next runner launch, such as 4G")
    r.add_argument("--cpu", help="CPU cap for the next runner launch, such as 400%%")
    r.add_argument("--account", help="switch agy account")
    r.add_argument("--prompt-file", help="read follow-up from PATH or '-' for stdin")
    r.add_argument("--detach", action="store_true", help="run in the background and return the job path")
    r.add_argument("--watch", **WATCH)
    r.add_argument("--group", type=groups.name, help="set the completion wake group for this job")
    gp = sub.add_parser("group", help="root-owned completion batching policy and membership")
    gc = gp.add_subparsers(dest="group_action", required=True)
    gs = gc.add_parser("set", help="configure a group before launching its members")
    gs.add_argument("owner")
    gs.add_argument("name")
    gs.add_argument("--wake", choices=("each", "all", "quiet"), required=True)
    gs.add_argument("--settle", type=groups.duration, default=60,
                    help="completion settle window (default 60s)")
    gs.add_argument("--remind", type=groups.duration, default=900,
                    help="unread reminder (default 15m; off disables)")
    gs.add_argument("--max-wait", type=groups.duration, help="all policy deadline, such as 30m")
    gs.add_argument("--repeat-reminders", action="store_true",
                    help="repeat reminders with exponential backoff")
    gs.add_argument("--members", nargs="*", default=[], help="declare member job names before launch")
    gl = gc.add_parser("list", help="show effective group policies")
    gl.add_argument("owner")
    clear = gc.add_parser("clear", help="reset a group's policy to the defaults")
    clear.add_argument("owner")
    clear.add_argument("name")
    ga = gc.add_parser("assign", help="set a group without resuming the job")
    ga.add_argument("job")
    ga.add_argument("name")
    gu = gc.add_parser("unassign", help="return a job to its owner's ungrouped policy")
    gu.add_argument("job")
    st = sub.add_parser("steer", help="send a message; resume idle jobs automatically")
    st.add_argument("job", help="job as <owner>/<name>")
    st.add_argument("text", nargs="?", help="steer text (use either this or --prompt-file)")
    st.add_argument("--prompt-file", help="read steer from PATH or '-' for stdin")
    delivery = st.add_mutually_exclusive_group()
    delivery.add_argument("--queue", action="store_true", help="queue only; do not start an idle job")
    delivery.add_argument(
        "--watch", nargs="?", const=1800, metavar="SECONDS",
        help="run detached, then stay until the first urgent event (default: 1800 seconds)",
    )
    for name in ("interrupt", "stop", "compact"):
        descriptions = {
            "interrupt": "request that the current turn end without stopping the job",
            "stop": "stop the job runner",
            "compact": "compact idle codex or claude history",
        }
        sub.add_parser(name, help=descriptions[name], description=descriptions[name]).add_argument(
            "job", help="job as <owner>/<name>"
        )
    sub.add_parser("owners", help="list owners, running jobs and unanswered urgent events")
    sub.add_parser("handoff", help="transfer one owner namespace to this root session").add_argument(
        "owner", help="owner whose jobs this root will take over"
    )
    h = sub.add_parser("heavy", help="wait for a shared heavy slot and host headroom, then run a command",
                       description="Heavy: model inference/benchmarks, dataset downloads/extraction, full "
                       "suites, long-lived servers/headless browsers, or >1 GiB/several cores for >1 minute. "
                       "Do not wrap runners, git, edits, reads, lint, type checks or targeted tests. "
                       "Wrap the whole foreground job; do not nest heavy calls. "
                       "Declare --mem SIZE (default 1G); use --exclusive only for timing measurements. "
                       "Root controls: heavy list, cancel <id|owner/job>, pause [--reason TEXT], resume. "
                       "Settings: AGENT_BRIDGE_HEAVY_SLOTS (optional hard cap), HEAVY_MIN_AVAILABLE_MIB "
                       "(max of 1024 and 20% effective RAM), HEAVY_MAX_LOAD (80% of CPU count); "
                       "all names use the AGENT_BRIDGE_ prefix.")
    h.add_argument("--memory-max-mib",
                   help="standalone scope RAM cap; inherited worker caps stay in place; warns if unavailable")
    h.add_argument("--mem", metavar="SIZE", help="expected peak memory, such as 1G or 2500M (default: 1G)")
    h.add_argument("--exclusive", action="store_true",
                   help="timing measurements only: exclude all other heavy jobs; never use for test suites")
    h.add_argument("argv", nargs=argparse.REMAINDER, help="-- <command> [arguments...]")
    peers = sub.add_parser("peers", help="list sibling jobs under this job's owner")
    peers.add_argument("job", nargs="?", help="job used to select the owner; defaults to AGENT_BRIDGE_JOB")
    result = sub.add_parser("result", help="print messages from a job's final turn")
    result.add_argument("job", help="job as <owner>/<name>")
    result.add_argument("--all", action="store_true", help="print every message from every turn")
    ack = sub.add_parser("ack", help="acknowledge urgent events displayed by watch")
    ack.add_argument("owner", nargs="+", help="owner or <owner>/<name>")
    retire = sub.add_parser("retire", help="archive and hide a stopped job; restorable until purged")
    retire.add_argument("job", help="job as <owner>/<name>")
    retire.add_argument("--keep-days", type=int, default=14,
                        help="days before purge eligibility (default: 14)")
    retire.add_argument("--purge", action="store_true", help="delete job data immediately; irreversible")
    sub.add_parser("restore", help="reactivate a retired job with its original session").add_argument("job")
    sub.add_parser("purge", help="delete expired retired jobs; archived reports remain").add_argument(
        "job", nargs="?", help="one <owner>/<name>; omit for all expired retired jobs"
    )
    w = sub.add_parser("watch", help="watch jobs under one or more owners, or a specific job")
    w.add_argument("owner", nargs="+", help="owner or <owner>/<name>")
    w.add_argument(
        "--until-event",
        action="store_true",
        help="wake on completion/failure, questions, errors or explicit blocking/URGENT messages",
    )
    w.add_argument("--include-info", action="store_true",
                   help="also wake on routine messages, slow/stall notices and other informational events")
    w.add_argument(
        "--stall-min",
        type=int,
        default=SILENCE_SECONDS // 60,
        help="override the snapshot classifier's silence threshold, in minutes",
    )
    w.add_argument(
        "--timeout",
        type=int,
        help="wait limit before exit 124; Codex continues through scheduled unread reminders",
    )
    for name in ("models", "quota"):
        x = sub.add_parser(
            name,
            help="list available models" if name == "models" else "show agy quota for signed-in accounts",
        )
        x.add_argument(
            "--backend",
            choices=("agy", "claude", "codex", "opencode") if name == "models" else ("agy",),
            required=True,
            help="backend to query",
        )
        x.add_argument(
            "--account", help="agy account name (defaults to a1 for models, all signed-in accounts for quota)"
        )
    stale = sub.add_parser("stale", help="render model and guide drift (refresh --check for JSON)")
    stale.add_argument("--accept", action="store_true", help="legacy alias for refresh --record --yes")
    rf = sub.add_parser(
        "refresh", help="propose, apply or discard a model reference refresh",
        description="Weekly: a sandboxed worker proposes a refreshed reference; you confirm it.",
    )
    action = rf.add_mutually_exclusive_group()
    action.add_argument("--force", action="store_true", help="run even if one ran in the last 7 days")
    action.add_argument("--apply", action="store_true", help="apply the waiting proposal after confirmation")
    action.add_argument("--check", action="store_true", help="read-only drift, age and stale guides as JSON")
    action.add_argument("--record", action="store_true", help="validate root edits and record source review")
    rf.add_argument("--yes", action="store_true", help="with --apply/--record: sources already re-checked")
    action.add_argument("--discard", action="store_true", help="drop the waiting proposal")
    if len(sys.argv) > 1:
        if sys.argv[1] == "backends":
            p.error("unknown command 'backends'; use models --backend <codex|agy|claude|opencode>")
        flags = sys.argv[2:sys.argv.index("--")] if "--" in sys.argv[2:] else sys.argv[2:]
        if sys.argv[1] == "steer" and any(arg.split("=", 1)[0] == "--message" for arg in flags):
            st.error("steer takes the message as a positional argument: agent-bridge steer <job> 'message'")
    a, extras = p.parse_known_args()
    if extras:
        if a.command == "steer" and a.text is None and len(extras) == 1 and not extras[0].startswith("-"):
            a.text = extras[0]
        elif a.command == "steer":
            st.error(
                "steer accepts one text; put text before --watch, use --watch=SECONDS, or use --prompt-file"
            )
        else:
            p.error(f"unrecognized arguments: {' '.join(extras)}")
    if a.command == "steer":
        if isinstance(a.watch, str):
            watch_value = a.watch
            try:
                a.watch = int(watch_value)
            except ValueError:
                if a.text is None and a.prompt_file is None:
                    a.text, a.watch = watch_value, 1800
                else:
                    try:
                        watch_seconds(watch_value)
                    except argparse.ArgumentTypeError as error:
                        st.error(str(error))
            else:
                if a.text is not None and a.text.isdecimal():
                    st.error(
                        "ambiguous numeric steer text with --watch seconds; put text before --watch, "
                        "use --watch=SECONDS, or use --prompt-file"
                    )
    runner_fd = None
    root_guard = ExitStack()
    try:
        if a.command == "waiting":
            from .status_model import DeclaredWait

            identity = os.environ.get("AGENT_BRIDGE_JOB")
            if not os.environ.get(WORKER_FLAG) or not identity:
                raise ValueError("waiting requires the worker's AGENT_BRIDGE_JOB environment")
            job = resolve_job(identity)
            if a.clear:
                if a.peer or a.note or any(arg.split("=", 1)[0] == "--for" for arg in sys.argv):
                    raise ValueError("--clear cannot be combined with declaration fields")
                waiting.write(job, None)
                print("waiting: cleared")
            else:
                peer = f"{job.parent.name}/{a.peer}" if a.peer else None
                if peer and (peer == identity or not (resolve_job(peer) / "state.json").is_file()):
                    raise ValueError("peer must be another existing sibling job")
                value = DeclaredWait(a.on, a.note, stamp(), a.duration, peer)
                waiting.write(job, value)
                log(job, "waiting_declared")
                print(f"waiting: {a.on} for {a.duration}s")
            return
        if a.command == "group":
            groups.require_root()
            if a.group_action in {"assign", "unassign"}:
                job = resolve_job(a.job)
                if not (job / "state.json").is_file():
                    raise ValueError("group assignment requires an existing job")
                with owner_binding.access(job.parent, root_identity()):
                    groups.assign(job, a.name if a.group_action == "assign" else None)
                print(f"group: {a.job} assigned to {a.name if a.group_action == 'assign' else '@ungrouped'}")
            else:
                owner = resolve_job(f"{groups.name(a.owner)}/placeholder").parent
                if a.group_action == "set":
                    if a.settle is None:
                        raise ValueError("settle needs a duration; use 0s for immediate each")
                    from .status_model import WakePolicy

                    policy = WakePolicy(a.wake, a.settle, a.remind, a.max_wait, a.repeat_reminders)
                    with owner_binding.access(owner, root_identity()):
                        groups.configure(owner, a.name, policy, a.members)
                    print(f"group: {a.owner}/{a.name} wake={a.wake} settle={a.settle}s")
                elif a.group_action == "clear":
                    with owner_binding.access(owner, root_identity()):
                        groups.clear(owner, a.name)
                    print(f"group: {a.owner}/{a.name} reset to each with 60s settle and 15m reminders")
                else:
                    data = groups.settings(owner, [])
                    from dataclasses import asdict

                    print(f"{a.owner}/@ungrouped "
                          + json.dumps(asdict(groups.DEFAULT_POLICY), sort_keys=True))
                    labels = set(data["policies"]) | {row["group"] for row in data["members"].values()}
                    for label in sorted(labels):
                        raw = data["policies"].get(label, asdict(groups.DEFAULT_POLICY))
                        print(f"{a.owner}/{label} " + json.dumps(raw, sort_keys=True))
            return
        if a.command == "heavy":
            if a.argv[:1] and a.argv[0] in {"list", "cancel", "pause", "resume"}:
                if a.mem is not None or a.exclusive or a.memory_max_mib is not None:
                    h.error("command flags cannot be combined with heavy queue controls")
                heavy_control.main(a.argv)
                return
            heavy.run(a.argv[1:] if a.argv[:1] == ["--"] else a.argv, a.memory_max_mib,
                      mem=a.mem, exclusive=a.exclusive)
            return
        if a.command == "guide":
            names = {"workflow": ("overview",), "plans": ("models",),
                     "subscriptions": ("subscriptions",), "sources": ("sources",),
                     "heavy": ("heavy",), "status": ("status",)}
            print(guide(*names.get(a.topic, ("overview", "models"))))
            return
        if a.command == "status":
            snapshot = status.Collector(JOBS).collect(a.owner, storage=a.storage,
                                                    include_quotas=not a.no_quotas)
            if a.json:
                print(json.dumps(snapshot.to_dict(), allow_nan=False))
            else:
                print(status_render.pressure(snapshot.pressure, snapshot.heavy))
                for job in snapshot.jobs:
                    if not job.retired_at:
                        print(status_render.job_status(job))
                for line in status_render.peer_conversations(snapshot):
                    print(line)
                print(f"unacknowledged completions: {snapshot.unacknowledged_completions}; "
                      f"oldest age={snapshot.oldest_unacknowledged_completion_age_seconds}s")
                for notice in snapshot.group_events:
                    print(status_render.group_notice(notice))
            return
        if a.command == "sessions":
            print(json.dumps(session_bindings()))
            return
        if a.command == "handoff":
            owner = resolve_job(f"{groups.name(a.owner)}/placeholder").parent
            owner_binding.handoff(owner, root_identity())
            print(f"handoff: {a.owner} now belongs to this root")
            return
        if a.command == "purge" and not a.job:
            failed = False
            for path in sorted(JOBS.glob("*/*/state.json")):
                try:
                    job = resolve_job(str(path.parent))
                    with owner_binding.access(job.parent, root_identity()):
                        if retirement.purge_due(load_state(job)):
                            print(retirement.purge(job))
                except (OSError, ValueError, RuntimeError) as exc:
                    print(f"skipped {path.parent.parent.name}/{path.parent.name}: {exc}", file=sys.stderr)
                    failed = True
            if failed:
                raise SystemExit(1)
            return
        if a.command == "stale":
            if a.accept:
                raise SystemExit(refresh.record(yes=True))
            found = reference.check()
            print("\n".join(found) if found else "the reference is current")
            raise SystemExit(1 if found else 0)
        if a.command == "refresh":
            if a.check:
                print(json.dumps(reference.inspect(), indent=2))
                return
            if a.record:
                raise SystemExit(refresh.record(a.yes))
            if a.discard:
                raise SystemExit(refresh.discard())
            raise SystemExit(refresh.apply(a.yes) if a.apply else refresh.run(a.force))
        if a.command == "start":
            if note := reference.warning():
                print(note, file=sys.stderr)
            a.title = a.title.strip()
            if (
                not 3 <= len(a.title) <= 48
                or len(a.title.splitlines()) != 1
                or a.title.casefold() == a.backend.casefold()
            ):
                raise RuntimeError(
                    "--title must be 3-48 characters on one line and cannot be just the backend name"
                )
        if a.command == "watch":
            if not watch(a.owner, a.until_event, a.stall_min, a.timeout, include_info=a.include_info):
                raise SystemExit(124)
            return
        if a.command == "ack":
            from .watch import job_dirs

            for job in job_dirs(a.owner):
                with owner_binding.access(job.parent, root_identity()):
                    acknowledge(job)
                print(f"acknowledged displayed events: {job.parent.name}/{job.name}")
            return
        if a.command == "owners":
            snapshot = status.Collector(JOBS).collect(include_quotas=False, storage=True)
            print(status_render.pressure(snapshot.pressure, snapshot.heavy))
            if snapshot.pressure.warning:
                print(f"WARNING: host overloaded: {snapshot.pressure.warning}; pause heavy work",
                      file=sys.stderr)
            for line in status_render.owners(snapshot):
                print(line)
            return
        if a.command == "peers":
            caller_job = os.environ.get("AGENT_BRIDGE_JOB")
            if os.environ.get(WORKER_FLAG) and a.job and a.job != caller_job:
                raise RuntimeError("workers can list only their own siblings")
            value = caller_job if os.environ.get(WORKER_FLAG) else a.job or caller_job
            if not value:
                raise RuntimeError("peers needs AGENT_BRIDGE_JOB or a <job> argument")
            job = resolve_job(value)
            snapshot = status.Collector(job.parent.parent).collect([job.parent.name], include_quotas=False)
            for line in status_render.peers(snapshot):
                print(line)
            return
        if a.command == "result":
            job = resolve_job(a.job)
            with owner_binding.access(job.parent, root_identity()):
                # Snapshot completions before reading; a concurrently arriving turn stays pending.
                completion = max((end for end, event in event_lines(job)
                                  if event.get("kind") == "turn_completed"), default=0)
                print(result_text(job, a.all) if (job / "state.json").exists() else
                      retirement.archived_result(ARCHIVE, f"{job.parent.name}/{job.name}"))
                sys.stdout.flush()
                if completion and not os.environ.get(WORKER_FLAG):
                    acknowledge(job, completion)
            return
        if a.command in ("models", "quota"):
            if a.backend == "agy":
                getattr(agy, a.command)(a.account or (None if a.command == "quota" else "a1"))
            elif a.backend == "claude":
                claude.models()
            elif a.backend == "opencode":
                opencode.models()
            else:
                codex.models()
            return
        job = resolve_job(a.job)
        if a.command in ROOT_COMMANDS or a.command == "compact":
            with owner_binding.guard(job.parent, root_identity()):
                pass
        if a.command == "retire":
            with owner_binding.access(job.parent, root_identity()):
                print(retirement.retire(job, ARCHIVE, result_text, a.keep_days, a.purge))
            return
        if a.command in ("restore", "purge"):
            with owner_binding.access(job.parent, root_identity()):
                print(getattr(retirement, a.command)(job))
            return
        if (job / "state.json").exists() and load_state(job).get("retiredAt"):
            raise RuntimeError(f"job is retired; run agent-bridge restore {a.job} before {a.command}")
        job.mkdir(parents=True, exist_ok=True)
        state_path = job / "state.json"
        if a.command == "steer":
            if (a.text is None) == (a.prompt_file is None):
                raise RuntimeError("steer takes exactly one of <text> or --prompt-file")
            text = a.text if a.text is not None else read_prompt(a.prompt_file)
            if not text.strip():
                raise RuntimeError("empty steer")
            before = (job / "live.jsonl").stat().st_size if (job / "live.jsonl").exists() else 0
            from .status import running

            with owner_binding.access(job.parent, root_identity()):
                with steer_lock(job):
                    state = load_state(job)
                    if state.get("retiredAt"):
                        raise RuntimeError(f"job is retired; run agent-bridge restore {a.job} first")
                    path = make_steer(job, text)
                    log(job, "root_steer", level="info", file=path.name)
                    if not a.queue:
                        try:
                            runner_fd = lock_runner(job)
                        except RuntimeError:
                            pass  # The live runner owns delivery, including its final queue check.
                        if runner_fd is not None and running(load_state(job)):
                            os.close(runner_fd)
                            runner_fd = None
            if a.queue:
                print(f"queued: {path}; deliver with agent-bridge resume {a.job}")
                return
            if runner_fd is None:
                print(path, flush=True)
                return follow(job, before, a.watch)
            a.detach, a.prompt_file = True, None
        if a.command in ("interrupt", "stop"):
            with owner_binding.access(job.parent, root_identity()):
                (job / a.command).touch()
            return
        if a.command == "compact" and load_state(job)["backend"] not in ("codex", "claude"):
            raise RuntimeError("compact is supported only by codex and claude")
        if a.command in ROOT_COMMANDS or a.command == "compact":
            root_guard.enter_context(owner_binding.access(job.parent, root_identity(), start=True))
        if runner_fd is None:
            runner_fd = lock_runner(job)
        if state_path.exists() and load_state(job).get("retiredAt"):
            raise RuntimeError(f"job is retired; run agent-bridge restore {a.job} first")
        resume = a.command in ("resume", "compact", "steer")
        if resume:
            state = load_state(job)
            state.pop("runnerPid", None)
            if a.command in ("resume", "steer"):
                state["autoAnswers"] = 0
            if a.command == "compact" and state.get("activeTurnId"):
                raise RuntimeError("job has an active turn; stop it before compacting")
            module = BACKENDS[state["backend"]]
            if getattr(a, "account", None):
                if state["backend"] != "agy":
                    raise RuntimeError("--account is supported only for agy resumes")
                agy.switch_account(job, state, a.account)
            for key in ("model", "effort"):
                if getattr(a, key, None):
                    state[key] = getattr(a, key)
        else:
            if state_path.exists():
                raise RuntimeError("job exists; use resume")
            if a.sandbox == "read-only" and a.writable_root:
                raise RuntimeError("--writable-root requires workspace-write")
            cwd = str(Path(a.cwd).expanduser().resolve())
            roots = list(
                dict.fromkeys([cwd, *[str(Path(x).expanduser().resolve()) for x in (a.writable_root or [])]])
            )
            state = {
                "version": 1,
                "backend": a.backend,
                "title": a.title,
                "cwd": cwd,
                "account": (a.account or "a1")
                if a.backend == "agy"
                else codex.active_account()
                if a.backend == "codex"
                else "",
                "model": a.model,
                "effort": a.effort,
                "sandbox": a.sandbox,
                "writableRoots": roots,
                "activeTurnId": None,
                "parent": root_identity(),
            }
            if a.backend == "codex":
                state.update(
                    threadId="",
                    config={},
                )
                for key, _, value in (z.partition("=") for z in a.config or []):
                    try:
                        state["config"][key] = json.loads(value)
                    except json.JSONDecodeError:
                        state["config"][key] = value
            if a.backend == "agy":
                state.update(
                    conversationId="", allow=a.allow or [], deny=a.deny or [], turnsSent=0, turnsDone=0
                )
            if a.backend == "claude":
                state.update(sessionId="")
            if a.backend == "opencode":
                state.update(sessionId="")
            (job / "steer").mkdir(exist_ok=True)
            (job / "inbox").mkdir(exist_ok=True)
        if a.command in {"start", "resume"}:
            caps = job_caps(state)
            if a.memory:
                caps["memoryMax"] = a.memory
            if a.cpu:
                caps["cpuQuota"] = a.cpu
            resources.validate_caps(caps["memoryMax"], caps["cpuQuota"])
            state.update(caps)
        if resume:
            prompt = read_prompt(a.prompt_file) if getattr(a, "prompt_file", None) else ""
            if a.command == "resume" and not prompt and not list((job / "steer").glob("[0-9]*.md")):
                prompt = "Continue."
        elif a.prompt_file:
            prompt = read_prompt(a.prompt_file)
            (job / "prompt.md").write_text(prompt + "\n", encoding="utf-8")
        else:
            prompt = read_prompt(job / "prompt.md")
        record_root_prompt = bool(prompt) and (
            a.command == "start" or (a.command == "resume" and bool(a.prompt_file))
        )
        save(state_path, state)
        if a.command in {"start", "resume"}:
            configured = groups.settings(job.parent, [])["members"].get(job.name)
            group = getattr(a, "group", None) or (configured["group"] if configured else None)
            if group is not None:
                groups.assign(job, group, new_turn=True)
        backend = module if resume else BACKENDS[a.backend]
        extra = {"compact": True} if a.command == "compact" else {}
        if a.command == "resume":
            count = len(list((job / "steer").glob("[0-9]*.md")))
            print(f"resume: delivering {count} queued steer(s)" if count else
                  "resume: continuing the same native session", flush=True)
        watching = getattr(a, "watch", None)
        launch_message = (f"delivered by resuming the idle job; watch: agent-bridge watch {a.job}"
                          if a.command == "steer" else str(job))
        if getattr(a, "detach", False) or watching:
            if a.command != "steer":
                before = (job / "live.jsonl").stat().st_size if (job / "live.jsonl").exists() else 0
            pid = os.fork()
            if pid:
                os.close(runner_fd)
                runner_fd = None
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    try:
                        current = json.loads(state_path.read_text())
                        runner_pid = current.get("runnerPid")
                    except (OSError, json.JSONDecodeError):
                        runner_pid = None
                    if runner_pid == pid and Path(f"/proc/{runner_pid}").exists():
                        print(launch_message, flush=True)
                        return follow(job, before, watching)
                    try:
                        exited, exit_status = os.waitpid(pid, os.WNOHANG)
                    except ChildProcessError:
                        exited = 0
                    if exited:
                        if os.WIFEXITED(exit_status) and os.WEXITSTATUS(exit_status) == 0:
                            print(launch_message, flush=True)
                            return follow(job, before, watching)
                        raise RuntimeError(f"detached runner exited before startup (status {exit_status})")
                    time.sleep(0.1)
                tail = (
                    (job / "runner.log").read_text(errors="replace")[-2000:]
                    if (job / "runner.log").exists()
                    else ""
                )
                raise RuntimeError(
                    f"detached runner did not start within 10 seconds; runner.log tail:\n{tail}"
                )
            os.setsid()
            null_fd = os.open(os.devnull, os.O_RDONLY)
            log_fd = os.open(job / "runner.log", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            os.dup2(null_fd, 0)  # release the caller's stdin pipe
            os.dup2(log_fd, 1)
            os.dup2(log_fd, 2)
            os.close(null_fd)
            os.close(log_fd)
            live_path = job / "live.jsonl"
            live_offset = live_path.stat().st_size if live_path.exists() else 0
            try:
                fd, runner_fd = runner_fd, None
                run_with_linger(
                    job, state, state_path, backend, prompt, resume, extra, fd,
                    root_prompt=record_root_prompt,
                )
            except Exception as exc:
                print(f"agent-bridge: {exc}", file=sys.stderr, flush=True)
                logged = False
                try:
                    with live_path.open("rb") as events:
                        events.seek(live_offset)
                        for line in events:
                            try:
                                event = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            if (
                                isinstance(event, dict)
                                and event.get("kind") == "error"
                                and event.get("message") == str(exc)
                            ):
                                logged = True
                                break
                except OSError:
                    pass
                if not logged:
                    log(job, "error", message=str(exc))
                os._exit(1)
            os._exit(0)
        print(job)
        fd, runner_fd = runner_fd, None
        run_with_linger(
            job, state, state_path, backend, prompt, resume, extra, fd,
            root_prompt=record_root_prompt,
        )
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        if runner_fd is not None:
            os.close(runner_fd)
        print(f"agent-bridge: {exc}", file=sys.stderr)
        raise SystemExit(1)
    finally:
        root_guard.close()


def follow(job, before, seconds):
    """--watch: after the detached start, stay until an urgent event, so the root backgrounds one command.

    Unacknowledged urgent events are replayed, including those before this launch."""
    owned = [f"{job.parent.name}/{job.name}"]
    if seconds is not None and not watch(owned, True, timeout=seconds, offsets={job: before}):
        raise SystemExit(124)


if __name__ == "__main__":
    main()

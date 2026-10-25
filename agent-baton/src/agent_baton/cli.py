import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

from agent_baton import ask as asking
from agent_baton import core, doctor, env_file, guard, inject, question, serve

STILL_HELD = 75  # EX_TEMPFAIL: not an error, ask again
OUTPUT_TAIL = 4000  # bytes of each stream handed back to the agent, to keep its context small
OUTCOMES = {
    "returned": (
        "returned: the human finished signing in to {site}. The browser is yours again; look at the "
        "page to confirm it worked. Never ask for the password or code."
    ),
    "cancelled": "cancelled: the human declined for {site}. Do not retry; report back.",
    "expired": "expired: nobody answered for {site}. Do not retry on your own; report and ask.",
    "withdrawn": "withdrawn: the question is no longer pending. This is not a human answer or approval.",
}
GONE = "the held answers for {site} are gone ({why}); `ask` again if you still need them."  # answered asks


def harness():
    if os.environ.get("AGENT_BATON_BY"):
        return os.environ["AGENT_BATON_BY"]
    if os.environ.get("CLAUDECODE"):
        return "Claude"
    if os.environ.get("CODEX_THREAD_ID"):
        return "Codex"
    return "An agent"


def clean_site(value):
    host = urlsplit(value).netloc if "://" in value else value
    if not host or len(host) > 100 or any(c.isspace() for c in host):
        sys.exit("site must be a hostname or URL")
    return host


def pick(ref, kind=None):
    """Select only this session's batons, including when an explicit id or site is given."""
    batons = [b for b in core.all_batons() if kind in (None, b["kind"])]
    if ref:
        matches = [b for b in batons if ref in (b["id"], b["site"])]
        if not matches:
            sys.exit(f"no baton matches {ref!r}")
        return matches[-1]
    open_ones = [b for b in batons if b["status"] == "held"]
    if len(open_ones) > 1:
        sys.exit("several batons are held; name one: " + ", ".join(b["id"] for b in open_ones))
    if open_ones:
        return open_ones[0]
    if batons:
        return batons[-1]
    sys.exit("no baton")


def start(args):
    cfg = core.config()
    site = clean_site(args.site)
    if any(item.lower() in site.lower() for item in cfg["deny"]):
        sys.exit(f"{site} is on the never-browse list; ask the human to do it themselves")
    baton = next((b for b in core.held("login") if b["site"] == site), None)
    baton = baton or launch(core.create(site, args.reason[:300], harness(), args.ttl or cfg["ttl"]))
    baton = reached(baton)
    channels = ", ".join(baton["notified"]) or "nobody"
    print(f"baton with the human: {site} [{baton['id']}], {core.left(baton)} left, notified: {channels}")
    print(
        f"Do not use the browser, screen or cua-driver until it returns. Run: agent-baton wait {baton['id']}"
    )
    return 0


def run(args):
    argv = args.argv[1:] if args.argv[:1] == ["--"] else args.argv
    if not argv:
        sys.exit("usage: agent-baton run [--reason R] -- <command> [args...]")
    cfg = core.config()
    baton = core.create(
        os.path.basename(argv[0]),
        args.reason[:300],
        harness(),
        args.ttl or cfg["ttl"],
        kind="run",
        argv=argv,
        command=shlex.join(argv),
        cwd=os.getcwd(),
        hold=args.ttl or cfg["ttl"],  # seconds the command may run once the human presses Run
    )
    baton = reached(launch(baton))
    channels = ", ".join(baton["notified"]) or "nobody"
    print(
        f"waiting for the human to approve and run [{baton['id']}]: {baton['command']} (notified: {channels})"
    )
    print(f"They type any password themselves. Run: agent-baton wait {baton['id']}")
    return 0


def launch(baton):
    core.sweep()
    subprocess.Popen(
        [sys.executable, "-m", "agent_baton.cli", "_serve", baton["id"]],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return baton


def reached(baton):
    """Wait for the daemon to report who it notified; if none could be, the human must be told in chat."""
    deadline = time.monotonic() + 8
    while "notified" not in baton and time.monotonic() < deadline:
        time.sleep(0.1)
        baton = core.load(baton["id"])
    if "notified" not in baton:
        core.resolve(baton["id"], "cancelled")
        sys.exit("the human page failed to start (is the configured port taken?); nothing was handed over")
    if not [c for c in baton["notified"] if "-failed" not in c]:
        fix = {
            "run": "ask them to run the command themselves",
            "login": f"then they run `agent-baton back {baton['id']}` in the originating session context",
            "ask": "ask them to enter the secret directly in the target app",
            "env": "ask them to store the secret themselves in the listed files",
            "question": "keep the original harness question pending; silence is not an answer",
        }[baton["kind"]]
        print(f"No channel reached the human: tell them in chat; {fix}.")
    return baton


def wait(args):
    baton = pick(args.baton)
    deadline = None if args.until_done else time.monotonic() + args.timeout  # until-done ends at expiry
    while (
        baton["status"] == "held"
        and not baton.get("answered")
        and (deadline is None or time.monotonic() < deadline)
    ):
        time.sleep(0.5)
        baton = core.load(baton["id"])
    if baton["kind"] == "question" and baton["status"] == "returned":
        result = (
            {"id": baton["id"], "title": baton["question"], "answers": baton["answers"]}
            if "form" in baton
            else {"id": baton["id"], "question": baton["question"], "answer": baton["answer"]}
        )
        print(json.dumps(result, ensure_ascii=False))
        return 0
    if baton["status"] == "held" and baton.get("answered"):
        names = ", ".join(f["name"] for f in baton["fields"])
        print(f"received: {names}. The daemon holds them privately for {core.left(baton)}.")
        print(f"Click the field, then run: agent-baton type <name> [--enter] --id {baton['id']}")
        return 0
    if baton["status"] == "held":
        print(f"still with the human ({core.left(baton)} left). Run agent-baton wait {baton['id']} again.")
        return STILL_HELD
    if baton["kind"] == "run" and baton["status"] == "returned":
        print(f"finished: `{baton['command']}` exited {baton['exit']}")
        for stream in ("out", "err"):
            text = output_tail(core.output_path(baton["id"], stream))
            if text:
                print(f"--- std{stream} ---\n{text}")
        return 0 if baton["exit"] == 0 else 1
    if baton["kind"] == "env" and baton.get("answered") and baton["status"] == "returned":
        print(f"stored {baton['name']} in {', '.join(baton['files'])}; backups: {baton['backup'] or 'none'}")
        return 0
    if baton["kind"] == "ask" and baton.get("answered") and baton["status"] != "cancelled":
        why = "forgotten" if baton["status"] == "returned" else "timed out"
        print(GONE.format(site=baton["site"], why=why))
        return 0
    print(OUTCOMES[baton["status"]].format(site=baton["site"]))
    return 0 if baton["status"] == "returned" else 1


def parse_field(spec):
    left, _, label = spec.partition("=")
    name, _, flag = left.partition(":")
    if not asking.NAME.match(name) or flag not in ("", "secret"):
        sys.exit(f"bad field {spec!r}: use name[:secret]=Label, with a lowercase name like email or password")
    return {"name": name, "label": (label or name)[:60], "secret": flag == "secret"}


def ask_form(args):
    cfg = core.config()
    fields = [parse_field(spec) for spec in args.fields]
    names = [f["name"] for f in fields]
    if not fields or len(set(names)) != len(names):
        sys.exit("give each field once, as name[:secret]=Label")
    for window in args.window:
        if any(term in window.lower() for term in cfg["no_type"]):
            sys.exit(f"{window!r} looks like a terminal or agent window, which `type` never types into")
    shown = " or ".join(args.window)
    ttl = args.ttl or cfg["ttl"]
    baton = core.create(
        shown,
        args.reason[:300],
        harness(),
        ttl,
        kind="ask",
        window=shown,  # what the human sees on the form
        windows=args.window,  # the titles `type` may use, tried in order
        fields=fields,
        answered=False,
        hold=ttl,  # seconds the answers are kept once given
    )
    baton = reached(launch(baton))
    channels = ", ".join(baton["notified"]) or "nobody"
    print(f"asked the human for {', '.join(names)} [{baton['id']}], to type into {shown!r}")
    print(f"notified: {channels}. You never see the answer. Run: agent-baton wait {baton['id']}")
    return 0


def env_secret(args):
    files = env_file.targets(args.file)
    if not env_file.NAME.fullmatch(args.name):
        sys.exit("variable name must match [A-Z][A-Z0-9_]*")
    if args.prefix and not env_file.VALUE.fullmatch(args.prefix):
        sys.exit("prefix must contain only letters, numbers, underscore, dot or hyphen")
    cfg = core.config()
    label = args.name
    ttl = args.ttl or cfg["ttl"]
    baton = core.create(
        ", ".join(str(path) for path in files),
        args.reason[:300],
        harness(),
        ttl,
        kind="env",
        name=args.name,
        prefix=args.prefix,
        files=[str(path) for path in files],
        fields=[{"name": args.name, "label": label, "secret": True}],
        answered=False,
    )
    baton = reached(launch(baton))
    print(f"requested {args.name} for {', '.join(baton['files'])} [{baton['id']}]")
    print(f"notified: {', '.join(baton['notified']) or 'nobody'}. The value stays out of agent output.")
    print(f"Run: agent-baton wait {baton['id']}")
    return 0


def ask_question(args):
    cfg = core.config()
    try:
        ttl = cfg["ttl"] if args.ttl is None else args.ttl
        if args.command == "form":
            baton = question.create_form(question.load_form(args.file), harness(), ttl)
        else:
            baton = question.create(
                args.question, args.option, args.reason, harness(), ttl, multiple=args.multiple
            )
    except (OSError, UnicodeError, ValueError) as error:
        sys.exit(str(error))
    baton = reached(launch(baton))
    channels = ", ".join(baton["notified"]) or "nobody"
    print(f"question with the human [{baton['id']}], notified: {channels}")
    print(
        f"The answer will be readable by you. In the background: agent-baton wait {baton['id']} --until-done"
    )
    return 0


def withdraw(args):
    baton = pick(args.id, "question")
    baton = question.complete(baton["id"])
    print(f"question [{baton['id']}]: {baton['status']}")
    return 0


def secret_input(args):
    baton = pick(args.id, "ask")
    if baton["status"] != "held" or not baton.get("answered"):
        sys.exit("nothing is held to type: ask first and wait for the answer")
    try:
        fields = [args.name] if args.command == "type" else []
        opts = {"enter": args.enter, "clear": args.clear} if args.command == "type" else {}
        reply = asking.request(baton["id"], args.command, fields, opts)
    except OSError:
        sys.exit("the held answers are gone (expired or forgotten); ask again")
    print(reply["text"])
    return reply["code"]


def forget(args):
    baton = pick(args.id, "ask")
    core.resolve(baton["id"], "returned")
    print(f"forgot the answers for {baton['site']} [{baton['id']}]")
    return 0


def windows(_):
    for title in inject.windows():
        print(title[:80])
    return 0


def output_tail(path):
    if not path.is_file():
        return ""
    data = path.read_bytes()
    text = data[-OUTPUT_TAIL:].decode(errors="replace").strip()
    return (
        f"(first {len(data) - OUTPUT_TAIL} bytes omitted; full output in {path})\n{text}"
        if len(data) > OUTPUT_TAIL
        else text
    )


def hand_back(status):
    def run(args):
        baton = pick(args.baton)
        if baton["status"] != "held":
            sys.exit(f"{baton['site']} [{baton['id']}] is already {baton['status']}")
        if baton["kind"] in ("run", "question") and status == "returned":
            sys.exit("commands finish and questions are answered on their page; `back` is only for logins")
        if baton["kind"] == "question":
            question.complete(baton["id"], declined=True)
        else:
            core.resolve(baton["id"], status)
        print(f"{baton['site']} [{baton['id']}] {status}")
        return 0

    return run


def status(_):
    batons = core.all_batons()
    if not batons:
        print("no baton")
    for b in batons:
        tail = f"{core.left(b)} left" if b["status"] == "held" else b["status"]
        what = {"run": lambda: b["command"], "ask": lambda: ",".join(f["name"] for f in b["fields"])}.get(
            b["kind"], lambda: b["reason"]
        )()[:60]
        print(f"{b['id']}  {b['kind']}  {b['site']}  {tail}  by {b['by']}  {what}".rstrip())
    return 0


def guide():
    """The full workflow, shown only by --help so the model reads it when it decides to."""
    if not any(flag in sys.argv[1:] for flag in ("-h", "--help")):
        return None
    return Path(__file__).with_name("guide.md").read_text(encoding="utf-8").strip()


def build_parser():
    parser = argparse.ArgumentParser(
        prog="agent-baton",
        description="Human handoffs: private secrets, approved commands and ordinary questions.",
        epilog=guide(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("mcp", help="serve native handoff tools over MCP stdio").set_defaults(run=mcp)
    p = sub.add_parser("question", help="agent: ask a nonsecret question; wait returns the human's answer")
    p.add_argument("question", help="the complete question; do not include secrets")
    p.add_argument(
        "--option", action="append", default=[], help="a choice; repeat for more (Other is included)"
    )
    p.add_argument(
        "--multiple", action="store_true", help="allow selecting several options; answer is a JSON list"
    )
    p.add_argument("--reason", default="", help="context the human needs to decide")
    p.add_argument("--ttl", type=int, help="seconds before expiry (default from config)")
    p.set_defaults(run=ask_question)
    p = sub.add_parser("form", help="agent: build a one-off nonsecret form from a JSON definition")
    p.add_argument("file", type=Path, help="JSON with title and questions; see agent-baton --help")
    p.add_argument("--ttl", type=int, help="seconds before expiry (default from config)")
    p.set_defaults(run=ask_question)
    p = sub.add_parser(
        "withdraw", help="agent: withdraw an obsolete ordinary question; never grants approval"
    )
    p.add_argument("id", help="the question's baton id")
    p.set_defaults(run=withdraw)
    p = sub.add_parser("pass", help="agent: hand the human a login (blocks browser tools via the guard)")
    p.add_argument("site", help="hostname or URL the human will sign in to")
    p.add_argument("--reason", default="", help="one line the human sees, e.g. 'to read the PR'")
    p.add_argument("--ttl", type=int, default=0, help="seconds before it expires (default from config)")
    p.set_defaults(run=start)
    p = sub.add_parser("ask", help="agent: ask the human for secrets on a form; you never see them")
    p.add_argument(
        "--window",
        required=True,
        action="append",
        help="part of the title of the window typed into; repeat if the title changes between steps",
    )
    p.add_argument("--reason", default="", help="one line the human sees")
    p.add_argument("--ttl", type=int, default=0, help="seconds to hold the answers (default from config)")
    p.add_argument(
        "fields", nargs="+", help="name[:secret]=Label, e.g. email='Account email' password:secret=Password"
    )
    p.set_defaults(run=ask_form)
    p = sub.add_parser("env", help="agent: have the human store a secret in environment files")
    p.add_argument("name", help="uppercase environment variable name")
    p.add_argument(
        "--file", required=True, action="append", type=Path, help="target file; repeat for multiple files"
    )
    p.add_argument("--prefix", default="", help="required beginning of the secret value")
    p.add_argument("--reason", default="", help="context the human sees")
    p.add_argument("--ttl", type=int, default=0, help="seconds before expiry (default from config)")
    p.set_defaults(run=env_secret)
    p = sub.add_parser(
        "type", help="agent: type a held secret into the approved window (click its field first)"
    )
    p.add_argument("name", help="the field name given to ask")
    p.add_argument("--enter", action="store_true", help="press Enter afterwards")
    p.add_argument("--clear", action="store_true", help="select all and delete what is in the field first")
    p.add_argument("--id", help="which ask, if several are held")
    p.set_defaults(run=secret_input)
    p = sub.add_parser("focus", help="agent: activate the approved window before clicking its field")
    p.add_argument("--id", help="which ask, if several are held")
    p.set_defaults(run=secret_input)
    p = sub.add_parser("forget", help="delete the held answers now")
    p.add_argument("id", nargs="?")
    p.set_defaults(run=forget)
    sub.add_parser("windows", help="list visible window titles, to choose ask --window").set_defaults(
        run=windows
    )
    p = sub.add_parser("run", help="agent: have the human approve and run a command that needs a password")
    p.add_argument("--reason", default="", help="one line the human sees")
    p.add_argument("--ttl", type=int, default=0, help="seconds before it expires (default from config)")
    p.add_argument("argv", nargs=argparse.REMAINDER, help="-- command [args...]")
    p.set_defaults(run=run)
    p = sub.add_parser("wait", help="agent: wait for the baton to come back (exit 75 = still held)")
    p.add_argument("baton", nargs="?", help="id or site in this session; default the only open (else latest)")
    p.add_argument("--timeout", type=int, default=100, help="seconds to wait this call")
    p.add_argument(
        "--until-done",
        action="store_true",
        help="ignore --timeout and wait until answered or expired; for background commands",
    )
    p.set_defaults(run=wait)
    for name, outcome, text in (
        ("back", "returned", "human: the login is done, give the agent its eyes back"),
        ("cancel", "cancelled", "human: decline; the agent is told not to retry"),
    ):
        p = sub.add_parser(name, help=text)
        p.add_argument("baton", nargs="?", help="id or site; default the only open baton")
        p.set_defaults(run=hand_back(outcome))
    sub.add_parser("status", help="list this session's batons").set_defaults(run=status)
    sub.add_parser(
        "doctor", help="check the toast, typing, hooks and phone path; says what to fix"
    ).set_defaults(run=lambda _: doctor.main())
    sub.add_parser("guard", help="PreToolUse hook (JSON on stdin)").set_defaults(run=lambda _: guard.main())
    sub.add_parser("_serve").add_argument("baton")
    return parser


def mcp(_):
    from agent_baton.mcp import server

    server.run(transport="stdio")
    return 0


def main():
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.command == "_serve":
            serve.serve(pick(args.baton)["id"])
            return 0
        return args.run(args)
    except ValueError as error:
        parser.error(str(error))


if __name__ == "__main__":
    sys.exit(main())

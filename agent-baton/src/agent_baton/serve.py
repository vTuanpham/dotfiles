"""The human side: a one-use page on loopback, plus the notification that points at it.

The daemon alone knows the page token (never written to disk or argv), so the agent cannot
answer for the human. For a command baton the daemon also owns the command's terminal: the
human approves the exact command, types any password here, and the agent only ever gets the
exit code and the command's stdout/stderr."""

import html
import http.server
import json
import os
import pty
import re
import secrets
import select
import signal
import time
from urllib.parse import parse_qs, urlsplit

from agent_baton import ask as asking
from agent_baton import core, notify, question

MAX_FORM = 4096
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
PAGE = """\
<!doctype html><html lang=en><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>agent-baton</title>
<style>
:root {{ color-scheme: light dark; --fg:#1b1b1f; --bg:#f6f5f2; --card:#fff; --accent:#c2410c; --muted:#6b6b72 }}
@media (prefers-color-scheme: dark) {{ :root {{ --fg:#ececf0; --bg:#17171a; --card:#222226; --accent:#fb923c; --muted:#9a9aa3 }} }}
body {{ font:17px/1.5 system-ui,sans-serif; background:var(--bg); color:var(--fg); margin:0; padding:2rem 1rem }}
main {{ max-width:32rem; margin:0 auto; background:var(--card); padding:1.6rem; border-radius:14px; overflow-wrap:anywhere }}
h1 {{ font-size:1.25rem; margin:0 0 .8rem }} .site {{ color:var(--accent); font-weight:600 }}
blockquote {{ margin:1rem 0; padding:.6rem .9rem; border-left:3px solid var(--accent); color:var(--muted) }}
pre {{ white-space:pre-wrap; word-break:break-all; background:var(--bg); padding:.7rem; border-radius:8px; font-size:.9rem }}
.btn {{ display:block; width:100%; box-sizing:border-box; text-align:center; padding:.85rem; border-radius:10px;
  margin-top:.8rem; text-decoration:none; border:1px solid var(--muted); background:none; color:var(--fg); font:inherit }}
.go {{ background:var(--accent); border-color:var(--accent); color:#fff; font-weight:600 }}
input, textarea {{ width:100%; box-sizing:border-box; padding:.7rem; font:inherit; border-radius:8px; border:1px solid var(--muted) }}
textarea {{ resize:vertical; min-height:6rem }}
fieldset {{ border:0; margin:1rem 0; padding:0; min-width:0 }} legend {{ font-weight:600; margin-bottom:.5rem }}
.option {{ display:flex; align-items:baseline; gap:.6rem; padding:.7rem; margin:.4rem 0; border:1px solid var(--muted); border-radius:8px }}
.option input {{ width:auto; flex-shrink:0; accent-color:var(--accent) }}
small {{ color:var(--muted) }}
</style>
<main>{content}</main>{script}"""
LOGIN = """\
<h1>{by} is waiting for you</h1>
<p>Sign in to <span class=site>{site}</span> in your own browser window, then press the button.
Until you do, the agent cannot look at your screen or use the browser.</p>
{reason}
<a class="btn go" href="/{token}/back">Done, hand it back</a>
<a class=btn href="/{token}/cancel">Cancel</a>
<p><small>Expires in {left}.</small></p>"""
APPROVE = """\
<h1>{by} wants to run a command</h1>
<pre>{command}</pre>
<p><small>in {cwd}, as you</small></p>
{reason}
<form method=post action="/{token}/run"><button class="btn go">Run it</button></form>
<form method=post action="/{token}/decline"><button class=btn>Decline</button></form>
<p><small>If it asks for a password you type it here. The agent never sees it. Expires in {left}.</small></p>"""
RUNNING = """\
<h1>Running</h1>
<pre>{command}</pre>
<p id=asking>{asking}</p>
<form id=reply method=post action="/{token}/type" style="opacity:{opacity}">
<input type=password name=secret autocomplete=current-password placeholder="Type here when it asks" autofocus>
<button class="btn go">Send</button></form>
<p><small>This page closes itself when the command finishes.</small></p>"""
ASKING = "It asks: <code>{prompt}</code>"
IDLE = "Nothing is asking for input right now. It is working."
POLL = """\
<script>
setInterval(async () => {{
  try {{
    const r = await fetch('/{token}/state'); if (!r.ok) throw 0;
    const s = await r.json(); const ask = document.getElementById('asking');
    if (s.prompt) {{ ask.textContent = 'It asks: '; const c = document.createElement('code'); c.textContent = s.prompt; ask.append(c); }}
    else {{ ask.textContent = {idle}; }}
    document.getElementById('reply').style.opacity = s.prompt ? 1 : 0.5;
    if (s.phase !== 'running') location.reload();
  }} catch (e) {{ document.querySelector('main').innerHTML = '<h1>Finished</h1><p>You can close this tab.</p>'; }}
}}, 1500);
</script>"""
ASK_FORM = """\
<h1>{by} needs {what}</h1>
{reason}
<p>What you enter is typed into the window titled <code>{window}</code> on your PC. The agent never sees it.</p>
<form method=post action="/{token}/answer">{inputs}<button class="btn go">Send</button></form>
<form method=post action="/{token}/decline"><button class=btn>Decline</button></form>
<p><small>Expires in {left}.</small></p>"""
ASK_INPUT = (
    '<p><label>{label}<br><input name="{name}" type="{kind}" autocomplete="{ac}" required></label></p>'
)
ASK_DONE = """\
<h1>Received</h1>
<p>The agent can type {names} for the next {left}. They are deleted when it finishes or this expires.</p>
<form method=post action="/{token}/forget"><button class=btn>Forget now</button></form>"""
LOGIN_ANSWERS = {"back": "Handed back. The agent carries on.", "cancel": "Cancelled. The agent was told."}
QUESTION = """\
<h1>{by} has a question</h1>
{title}
{reason}
<form method=post action="/{token}/answer">
{fields}
<p><small>Your answer is shared with the agent and saved locally. Do not enter passwords, codes or keys.</small></p>
<button class="btn go">Send answer</button></form>
<form method=post action="/{token}/decline"><button class=btn>Decline</button></form>
<p><small>Expires in {left}. No answer is selected for you.</small></p>"""


def question_inputs(item, prefix=""):
    options = ""
    required = item.get("required", True)
    if item["options"]:
        choices = [*enumerate(item["options"]), ("other", "Other — write your answer below")]
        multiple = item["multiple"]
        kind = "checkbox" if multiple else "radio"
        radio_required = "required" if required and not multiple else ""
        legend = "Choose one or more" if multiple else "Choose one"
        options = (
            f"<fieldset><legend>{legend}</legend>"
            + "".join(
                f'<label class=option><input type={kind} name="{prefix}choice" value="{index}" {radio_required}>'
                f"<span>{html.escape(label)}</span></label>"
                for index, label in choices
            )
            + "</fieldset>"
        )
    label = "If you choose Other, write your answer here" if options else "Your answer"
    text_required = "required" if required and not options else ""
    optional = " (optional)" if not required else ""
    return (
        f"<fieldset><legend>{html.escape(item['question'])}{optional}</legend>{options}"
        f'<p><label for="{prefix}answer">{label}</label></p>'
        f'<textarea id="{prefix}answer" name="{prefix}answer" maxlength="{question.MAX_ANSWER}" '
        f"{text_required}></textarea></fieldset>"
    )


def question_page(baton, token):
    fields = (
        "".join(question_inputs(item, f"{item['id']}.") for item in baton["form"])
        if "form" in baton
        else question_inputs(baton)
    )
    return QUESTION.format(
        by=html.escape(baton["by"]),
        title=f"<p class=site>{html.escape(baton['question'])}</p>" if "form" in baton else "",
        reason=reason_block(baton),
        fields=fields,
        token=token,
        left=core.left(baton),
    )


class Command:
    """A command running on a pty only this daemon holds. Its stdout/stderr go to files; the pty
    carries just the terminal prompts (sudo, ssh, gpg), which are shown to the human and dropped."""

    def __init__(self, baton):
        self.baton = baton
        self.pid = self.master = self.exit = None
        self.approved = False  # set by a page thread; the main loop does the fork
        self.seen = ""

    @property
    def phase(self):
        return "approve" if not self.approved else "done" if self.exit is not None else "running"

    @property
    def prompt(self):
        lines = (line.strip() for line in reversed(self.seen.replace("\r", "").split("\n")))
        return next((line for line in lines if line), "")

    def start(self):
        out, err = (
            os.open(core.output_path(self.baton["id"], s), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            for s in ("out", "err")
        )
        self.pid, self.master = pty.fork()
        if self.pid == 0:
            try:
                os.dup2(out, 1)
                os.dup2(err, 2)
                os.chdir(self.baton["cwd"])
                os.execvp(self.baton["argv"][0], self.baton["argv"])
            except Exception as error:  # noqa: BLE001
                os.write(2, f"{error}\n".encode())
            os._exit(127)
        os.close(out)
        os.close(err)

    def pump(self):
        if self.phase != "running" or self.pid is None:
            return
        if select.select([self.master], [], [], 0)[0]:
            try:
                chunk = os.read(self.master, 4096).decode(errors="replace")
            except OSError:  # EIO: the child closed its end
                chunk = ""
            self.seen = (self.seen + ANSI.sub("", chunk))[-400:]
        done, status = os.waitpid(self.pid, os.WNOHANG)
        if done:
            self.exit = os.waitstatus_to_exitcode(status)
            os.close(self.master)

    def type(self, text):
        if self.phase == "running" and self.master is not None:
            os.write(self.master, text.encode() + b"\n")
            self.seen = ""  # the prompt was answered; don't keep showing it while the command works

    def stop(self):
        if self.phase != "running" or self.pid is None:
            return
        for sig in (signal.SIGTERM, signal.SIGKILL):
            os.killpg(self.pid, sig)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                if os.waitpid(self.pid, os.WNOHANG)[0]:
                    self.exit = -1
                    os.close(self.master)
                    return
                time.sleep(0.05)


def render(content, script=""):
    return PAGE.format(content=content, script=script).encode()


def reason_block(baton):
    return f"<blockquote>Agent says: {html.escape(baton['reason'])}</blockquote>" if baton["reason"] else ""


def ask_page(baton, token):
    if baton.get("answered"):
        names = ", ".join(html.escape(f["label"]) for f in baton["fields"])
        return ASK_DONE.format(names=names, left=core.left(baton), token=token)
    inputs = "".join(
        ASK_INPUT.format(
            label=html.escape(f["label"]),
            name=f["name"],
            kind="password" if f["secret"] else "text",
            ac=asking.autocomplete(f["name"]),
        )
        for f in baton["fields"]
    )
    return ASK_FORM.format(
        by=html.escape(baton["by"]),
        what=html.escape(" and ".join(f["label"] for f in baton["fields"])),
        reason=reason_block(baton),
        window=html.escape(baton["window"]),
        inputs=inputs,
        token=token,
        left=core.left(baton),
    )


def make_handler(baton_id, token, hosts, command, asker):
    class Handler(http.server.BaseHTTPRequestHandler):
        timeout = 10  # a browser's idle speculative connection must not hold a thread forever

        def log_message(self, *_):  # the token is in the path; keep it out of any log
            pass

        def send(self, code, body, kind="text/html; charset=utf-8", location=None):
            self.send_response(code)
            for header, value in (
                ("Content-Type", kind),
                ("Content-Length", str(len(body))),
                ("Cache-Control", "no-store"),
                ("Referrer-Policy", "no-referrer"),
                ("X-Frame-Options", "DENY"),
                (
                    "Content-Security-Policy",
                    "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
                    "connect-src 'self'; form-action 'self'",
                ),
                *([("Location", location)] if location else []),
            ):
                self.send_header(header, value)
            self.end_headers()
            self.wfile.write(body)

        def route(self):
            """The path after the token, or None when this request is not for the human."""
            parts = urlsplit(self.path).path.strip("/").split("/")
            baton = core.load(baton_id)
            ok = (
                self.headers.get("Host") in hosts  # a rebinding page would arrive with its own Host
                and secrets.compare_digest(parts[0].encode(), token.encode())
                and baton["status"] == "held"
            )
            return (parts[1:] if ok else None), baton

        def missing(self):
            self.send(404, b"not found", "text/plain")

        def do_GET(self):
            rest, baton = self.route()
            if rest is None:
                return self.missing()
            if baton["kind"] == "login":
                return self.login_get(rest, baton)
            if baton["kind"] == "ask":
                return self.missing() if rest else self.send(200, render(ask_page(baton, token)))
            if baton["kind"] == "question":
                return self.missing() if rest else self.send(200, render(question_page(baton, token)))
            if rest == ["state"]:
                state = {"phase": command.phase, "prompt": command.prompt}
                return self.send(200, json.dumps(state).encode(), "application/json")
            if rest:
                return self.missing()
            if command.phase == "approve":
                page = APPROVE.format(
                    by=html.escape(baton["by"]),
                    command=html.escape(baton["command"]),
                    cwd=html.escape(baton["cwd"]),
                    reason=reason_block(baton),
                    token=token,
                    left=core.left(baton),
                )
                return self.send(200, render(page))
            prompt = command.prompt
            running = RUNNING.format(
                command=html.escape(baton["command"]),
                asking=ASKING.format(prompt=html.escape(prompt)) if prompt else IDLE,
                opacity=1 if prompt else 0.5,
                token=token,
            )
            self.send(200, render(running, POLL.format(token=token, idle=json.dumps(IDLE))))

        def login_get(self, rest, baton):
            if rest == []:
                page = LOGIN.format(
                    by=html.escape(baton["by"]),
                    site=html.escape(baton["site"]),
                    reason=reason_block(baton),
                    token=token,
                    left=core.left(baton),
                )
                return self.send(200, render(page))
            if rest in (["back"], ["cancel"]):
                core.resolve(baton_id, "returned" if rest == ["back"] else "cancelled")
                return self.send(
                    200,
                    render(f"<h1>{LOGIN_ANSWERS[rest[0]]}</h1><p><small>You can close this tab.</small></p>"),
                )
            self.missing()

        def do_POST(self):
            rest, baton = self.route()
            if rest is None or baton["kind"] not in ("run", "ask", "question") or len(rest) != 1:
                return self.missing()
            try:
                size = int(self.headers.get("Content-Length") or 0)
                if size < 0:
                    raise ValueError
            except ValueError:
                return self.send(400, b"invalid content length", "text/plain")
            count = len(baton.get("form", [None]))
            limit = (question.MAX_ANSWER * 12 + 1024) * count if baton["kind"] == "question" else MAX_FORM
            if size > limit:
                return self.send(413, b"too large", "text/plain")
            try:
                form = parse_qs(
                    self.rfile.read(size).decode("utf-8"),
                    keep_blank_values=True,
                    errors="strict",
                    max_num_fields=12 * count if baton["kind"] == "question" else None,
                )
            except (UnicodeError, ValueError):
                return self.send(400, b"invalid form", "text/plain")
            action = rest[0]
            if baton["kind"] == "question":
                if action not in ("answer", "decline"):
                    return self.missing()
                try:
                    done = question.complete(baton_id, form if action == "answer" else None, declined=True)
                except ValueError as error:
                    return self.send(400, str(error).encode(), "text/plain; charset=utf-8")
                text = (
                    "Answer sent. The agent can continue."
                    if done["status"] == "returned"
                    else "Question closed."
                )
                return self.send(200, render(f"<h1>{text}</h1><p>You can close this tab.</p>"))
            if baton["kind"] == "ask":
                if action == "answer" and not baton.get("answered"):
                    values = {f["name"]: form.get(f["name"], [""])[0] for f in baton["fields"]}
                    if not all(values.values()):
                        return self.send(400, b"every field is required", "text/plain")
                    asker.answer(values)
                    notify.dismiss(baton)  # answered: take the toast off the screen
                elif action == "decline":
                    core.resolve(baton_id, "cancelled")
                elif action == "forget":
                    core.resolve(baton_id, "returned")
                else:
                    return self.missing()
                return self.send(303, b"", location=f"/{token}")
            if action == "run" and command.phase == "approve":
                command.approved = True
                hold = baton.get("hold", 600)  # the time limit starts when the human presses Run
                core.save({**core.load(baton_id), "expires": core.now() + hold})
                notify.dismiss(baton)
            elif action == "type":
                command.type(form.get("secret", [""])[0])
            elif action == "decline":
                core.resolve(baton_id, "cancelled")
            else:
                return self.missing()
            self.send(303, b"", location=f"/{token}")

    return Handler


def serve(baton_id):
    cfg = core.config()
    token = secrets.token_urlsafe(32)
    baton = core.load(baton_id)
    command = Command(baton) if baton["kind"] == "run" else None
    asker = asking.Ask(baton, cfg) if baton["kind"] == "ask" else None
    if asker:
        asker.start()
    hosts = set()  # filled once the port is known; the handler reads it per request
    handler = make_handler(baton_id, token, hosts, command, asker)
    phone, base = bool(cfg["url"]), urlsplit(cfg["url"])
    slots = [cfg["port"] + slot for slot in range(cfg["slots"])] if cfg["port"] else [0]
    for slot, local in enumerate(slots):  # one local port per open baton, each forwarded by Tailscale
        try:
            server = http.server.ThreadingHTTPServer(("127.0.0.1", local), handler)
            break
        except OSError:
            continue
    else:  # every phone port is busy: this baton is local-only
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        phone, cfg = False, {**cfg, "ntfy": ""}
    server.timeout = 0.2
    port = server.server_address[1]
    hosts |= {f"127.0.0.1:{port}", f"localhost:{port}"}
    public = None
    if phone:  # slot k is reached at the base URL's port plus k (tailscale serve --tcp=80+k)
        reach = (base.port or 80) + slot
        netloc = base.hostname + (f":{reach}" if reach != 80 else "")
        hosts.add(netloc)
        public = f"{base.scheme}://{netloc}/{token}"
    sent = notify.notify(baton, f"http://localhost:{port}/{token}", cfg, public)
    core.save({**core.load(baton_id), "port": port, "notified": sent})  # a fast answer may have landed
    while core.load(baton_id)["status"] == "held":
        server.handle_request()
        if asker:
            asker.tick()
        if command:
            if command.approved and command.pid is None:
                command.start()
            command.pump()
            if command.phase == "done":
                core.save({**core.load(baton_id), "status": "returned", "exit": command.exit})
    if command:
        command.stop()  # declined, expired or cancelled mid-run
    if asker:
        asker.stop()  # forgets every secret
    server.server_close()
    notify.dismiss(baton)

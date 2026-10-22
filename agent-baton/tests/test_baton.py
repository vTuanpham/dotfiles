import base64
import io
import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

from agent_baton import cli, core, doctor, guard, notify, question, serve

dismissed = []  # ids whose toast the daemon took down


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "BATONS", tmp_path / "batons")
    monkeypatch.setattr(core, "CONFIG", tmp_path / "config.toml")
    monkeypatch.delenv("CLAUDECODE", raising=False)
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.delenv("AGENT_BATON_BY", raising=False)
    monkeypatch.setenv("AGENT_BATON_SESSION", "test-session")
    monkeypatch.setattr(notify, "dismiss", lambda baton: dismissed.append(baton["id"]))
    dismissed.clear()


def verdict(tool_name, **tool_input):
    return guard.decide({"tool_name": tool_name, "tool_input": tool_input}, core.config(), core.held("login"))


def run_guard(monkeypatch, event):
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(json.dumps(event)))
    return guard.main()


def open_serve(monkeypatch, baton_id):
    """Run the human page in a thread; the 'notification' hands us its link."""
    links = []
    monkeypatch.setattr(
        notify, "notify", lambda baton, link, cfg, public=None: links.append(link) or ["test"]
    )
    thread = threading.Thread(target=serve.serve, args=(baton_id,), daemon=True)
    thread.start()
    for _ in range(100):
        if links and "notified" in core.load(baton_id):
            return links[0], thread
        threading.Event().wait(0.05)
    raise AssertionError("page never came up")


def get(url, host=None):
    request = urllib.request.Request(url, headers={"Host": host} if host else {})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.read().decode(), response.headers
    except urllib.error.HTTPError as error:
        return error.code, "", error.headers


def test_guard_is_open_without_a_baton_and_shut_with_one():
    assert verdict("mcp__claude-in-chrome__computer") is None
    core.create("github.com", "", "Codex", 600)
    for name in (
        "mcp__claude-in-chrome__computer",
        "mcp__Claude_Browser__navigate",
        "mcp__playwright__click",
    ):
        assert "github.com" in verdict(name)
    assert verdict("mcp__wake__tidy_scan") is None and verdict("Read", file_path="/x") is None
    assert verdict("mcp__claude_ai_Gmail__search") is None
    assert "cua-driver" not in (verdict("Bash", command="ls") or "")


@pytest.mark.parametrize(
    "tool, field, command",
    [
        ("Bash", "command", "cua-driver call screenshot"),
        ("Bash", "command", "rtk cua-driver call screenshot"),
        ("exec_command", "cmd", "bash -c 'npx playwright test'"),
        ("Bash", "command", "agent-baton wait && cua-driver call screenshot"),
        ("Bash", "command", "agent-baton wait $(cua-driver call screenshot)"),
    ],
)
def test_guard_shuts_shell_routes_to_the_screen_even_when_chained(tool, field, command):
    core.create("github.com", "", "Codex", 600)
    assert verdict(tool, **{field: command})


def test_agent_can_use_the_baton_cli_but_never_hand_it_back():
    core.create("github.com", "", "Codex", 600)
    assert verdict("Bash", command="agent-baton wait b7f3 --timeout 100") is None
    assert verdict("Bash", command="agent-baton pass x.com --reason 'cua-driver login'") is None
    for command in (
        "agent-baton back",
        "rtk agent-baton cancel b7f3",
        "agent-baton status; agent-baton back",
        "python -m agent_baton.cli cancel",
    ):
        assert "Only the human" in verdict("Bash", command=command)
    for command in (  # "back" in a path, a reason or a search is not the subcommand
        "cd ~/dotfiles/agent-baton && rg back src",
        "agent-baton ask --window Sign --reason 'come back later' email=Email",
    ):
        assert verdict("Bash", command=command) is None


def test_deny_list_holds_with_no_baton_and_only_for_browser_tools():
    assert "never-browse" in verdict(
        "mcp__claude-in-chrome__navigate", url="chrome://password-manager/passwords"
    )
    assert "never-browse" in verdict("Bash", command="cua-driver call click https://my.1password.com/x")
    assert verdict("Bash", command="curl https://1password.com/docs") is None
    core.CONFIG.write_text('deny = ["mybank.example"]')
    assert verdict("mcp__playwright__navigate", url="https://mybank.example/login")
    assert verdict("mcp__playwright__navigate", url="https://1password.com")  # defaults still apply


def test_expired_baton_stops_blocking_even_if_its_daemon_died():
    baton = core.create("github.com", "", "Codex", 600)
    baton["expires"] = core.now() - 1
    core.save(baton)
    assert core.held() == [] and core.load(baton["id"])["status"] == "expired"
    assert verdict("mcp__claude-in-chrome__computer") is None


def test_guard_main_exit_codes_and_fail_closed(monkeypatch, capsys):
    event = {"tool_name": "mcp__claude-in-chrome__computer", "tool_input": {}}
    assert run_guard(monkeypatch, event) == 0
    core.create("github.com", "", "Codex", 600)
    assert run_guard(monkeypatch, event) == 2 and "baton is with the human" in capsys.readouterr().err
    monkeypatch.setattr(guard, "decide", lambda *_: 1 / 0)
    assert run_guard(monkeypatch, {"tool_name": "Read"}) == 2  # broken guard + baton out = closed
    for baton in core.held():
        core.resolve(baton["id"], "returned")
    assert run_guard(monkeypatch, {"tool_name": "Read"}) == 0  # broken guard + nothing out = open


def test_human_page_is_one_use_token_and_host_bound(monkeypatch):
    baton = core.create("github.com", "<script>alert(1)</script>", "Codex", 600)
    link, thread = open_serve(monkeypatch, baton["id"])
    token = link.rsplit("/", 1)[1]
    base = link.rsplit("/", 1)[0]
    assert get(f"{base}/not-the-token")[0] == 404
    assert get(link, host="evil.example")[0] == 404
    code, page, headers = get(link)
    assert code == 200 and "Codex is waiting" in page and "github.com" in page
    assert "<script>" not in page and "&lt;script&gt;" in page
    assert headers["Cache-Control"] == "no-store" and headers["X-Frame-Options"] == "DENY"
    assert core.load(baton["id"])["status"] == "held"
    assert token not in json.dumps(core.load(baton["id"]))  # the agent can read this file
    assert get(f"{link}/back")[0] == 200
    thread.join(5)
    assert not thread.is_alive() and core.load(baton["id"])["status"] == "returned"
    assert dismissed == [baton["id"]]  # no stale toast button left behind


def test_ask_form_answers_are_held_and_only_typed_into_the_approved_window(monkeypatch, capsys):
    typed = []
    monkeypatch.setattr(
        cli.inject,
        "type_into",
        lambda window, text, enter, deny, clear=False: (
            typed.append((window, text, enter, deny, clear)) or "typed"
        ),
    )
    secret = "hunter2-dummy"
    threads = []

    def fake_popen(cmd, **_):
        threads.append(threading.Thread(target=serve.serve, args=(cmd[-1],), daemon=True))
        threads[-1].start()

    monkeypatch.setattr(cli.subprocess, "Popen", fake_popen)
    links = []
    monkeypatch.setattr(
        notify, "notify", lambda baton, link, cfg, public=None: links.append((baton, link)) or ["toast"]
    )
    argv = ["agent-baton", "ask", "--window", "Google Accounts", "--reason", "<b>sign in</b>"]
    monkeypatch.setattr("sys.argv", [*argv, "email=Account email", "password:secret=Password"])
    assert cli.main() == 0
    baton, link = links[0]
    assert baton["kind"] == "ask" and "Account email, Password" in notify.headline(baton)
    page = get(link)[1]
    assert "Google Accounts" in page and "&lt;b&gt;sign in" in page  # the target is shown, agent text escaped
    assert page.count('type="password"') == 1 and 'autocomplete="username"' in page
    assert post(f"{link}/answer", email="me@example.test") == 400  # every field is required
    monkeypatch.setattr("sys.argv", ["agent-baton", "type", "password"])
    with pytest.raises(SystemExit, match="nothing is held"):
        cli.main()  # nothing is typed before the human answers
    assert post(f"{link}/answer", email="me@example.test", password=secret) == 303
    capsys.readouterr()
    monkeypatch.setattr("sys.argv", ["agent-baton", "wait"])
    assert cli.main() == 0
    received = capsys.readouterr().out
    assert "received: email, password" in received and secret not in received
    monkeypatch.setattr("sys.argv", ["agent-baton", "type", "password", "--enter"])
    assert cli.main() == 0 and capsys.readouterr().out.strip() == "typed"
    assert typed == [("Google Accounts", secret, True, core.config()["no_type"], False)]
    monkeypatch.setattr("sys.argv", ["agent-baton", "type", "nope"])
    assert cli.main() == 1 and "no secret named" in capsys.readouterr().out
    everything = json.dumps(core.load(baton["id"])) + capsys.readouterr().out
    assert secret not in everything and "me@example.test" not in everything  # held in memory only
    monkeypatch.setattr("sys.argv", ["agent-baton", "forget"])
    assert cli.main() == 0
    threads[0].join(5)
    assert not threads[0].is_alive() and not asking_sock(baton["id"]).exists()
    assert secret not in "".join(p.read_text() for p in core.BATONS.iterdir() if p.is_file())


def asking_sock(baton_id):
    return cli.asking.sock_path(baton_id)


def test_ask_refuses_terminals_bad_fields_and_declines(monkeypatch):
    monkeypatch.setattr(cli.subprocess, "Popen", lambda cmd, **_: None)
    for window, field, why in (
        ("Windows Terminal", "x=X", "terminal"),
        ("Chrome", "Bad Name=X", "bad field"),
        ("Chrome", "x:wrong=X", "bad field"),
    ):
        monkeypatch.setattr("sys.argv", ["agent-baton", "ask", "--window", window, field])
        with pytest.raises(SystemExit, match=why):
            cli.main()
    monkeypatch.setattr("sys.argv", ["agent-baton", "ask", "--window", "Chrome", "x=X", "x=Y"])
    with pytest.raises(SystemExit, match="each field once"):
        cli.main()
    baton = core.create(
        "Chrome",
        "",
        "Codex",
        600,
        kind="ask",
        window="Chrome",
        answered=False,
        hold=600,
        fields=[{"name": "code", "label": "Code", "secret": False}],
    )
    link, thread = open_serve(monkeypatch, baton["id"])
    assert post(f"{link}/decline") == 303
    thread.join(5)
    assert core.load(baton["id"])["status"] == "cancelled" and dismissed == [baton["id"]]


def test_inject_script_never_carries_the_secret_on_a_command_line(monkeypatch):
    monkeypatch.setattr(cli.inject.x11, "type_into", lambda *args: None)  # no WSLg window matches
    calls = []
    monkeypatch.setattr(
        cli.inject.subprocess,
        "run",
        lambda cmd, **kw: calls.append((cmd, kw)) or type("R", (), {"returncode": 0, "stdout": ""})(),
    )
    monkeypatch.setattr(cli.inject.shutil, "which", lambda _: "powershell.exe")
    assert cli.inject.type_into("Sign in", "s3cr3t-dummy", True, ["terminal"]) == "typed and pressed Enter"
    ((cmd, kw),) = calls
    assert "s3cr3t-dummy" not in " ".join(cmd) and "s3cr3t-dummy" not in base64.b64decode(cmd[-1]).decode(
        "utf-16-le"
    )
    assert json.loads(kw["input"]) == {
        "window": "Sign in",
        "text": "s3cr3t-dummy",
        "enter": True,
        "deny": ["terminal"],
        "clear": False,
    }
    monkeypatch.setattr(
        cli.inject.subprocess, "run", lambda cmd, **kw: type("R", (), {"returncode": 5, "stdout": ""})()
    )
    assert "never-type list" in cli.inject.type_into("Sign in", "x", False, [])


def test_type_tries_each_approved_window_until_one_matches(monkeypatch):
    seen = []

    def fake(window, text, enter, deny, clear=False):
        seen.append(window)
        return cli.asking.NO_WINDOW if window == "Sign in" else "typed"

    monkeypatch.setattr(cli.inject, "type_into", fake)
    ask = cli.asking.Ask({"id": "x1", "windows": ["Sign in", "Welcome"]}, core.config())
    ask.secrets = {"password": "p"}
    assert ask.handle("type", ["password"], {"clear": True}) == {"text": "typed", "code": 0}
    assert seen == ["Sign in", "Welcome"]  # Google renames the window between its steps


def test_help_carries_the_full_workflow_but_normal_runs_do_not_load_it(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["agent-baton", "--help"])
    with pytest.raises(SystemExit):
        cli.main()
    helped = capsys.readouterr().out
    assert "ask + type" in helped and "agent-baton wait <id>" in helped and "name[:secret]=Label" in helped
    monkeypatch.setattr("sys.argv", ["agent-baton", "status"])
    assert cli.guide() is None  # the guide is read only when --help is asked for


def test_idle_browser_connections_do_not_stall_the_page(monkeypatch):
    import socket

    baton = core.create("github.com", "", "Codex", 600)
    link, thread = open_serve(monkeypatch, baton["id"])
    port = core.load(baton["id"])["port"]
    idle = [socket.create_connection(("127.0.0.1", port)) for _ in range(3)]  # Chrome's preconnects
    try:
        assert get(link)[0] == 200  # a one-at-a-time server would sit on the first idle socket
        assert get(f"{link}/back")[0] == 200
    finally:
        for sock in idle:
            sock.close()
    thread.join(5)
    assert core.load(baton["id"])["status"] == "returned"


def test_cli_end_to_end_pass_wait_back(monkeypatch, capsys):
    started = {}

    def fake_popen(cmd, **_):
        started["thread"] = threading.Thread(target=serve.serve, args=(cmd[-1],), daemon=True)
        started["thread"].start()

    monkeypatch.setattr(cli.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(notify, "notify", lambda *a, **k: ["toast"])
    monkeypatch.setenv("CODEX_THREAD_ID", "t")
    monkeypatch.setattr(
        "sys.argv", ["agent-baton", "pass", "https://github.com/login", "--reason", "read PR"]
    )
    assert cli.main() == 0
    out = capsys.readouterr().out
    assert "github.com" in out and "notified: toast" in out and "agent-baton wait" in out
    assert core.held()[0]["by"] == "Codex"
    monkeypatch.setattr("sys.argv", ["agent-baton", "wait", "--timeout", "0"])
    assert cli.main() == cli.STILL_HELD
    monkeypatch.setattr("sys.argv", ["agent-baton", "pass", "github.com"])
    assert cli.main() == 0 and len(core.held()) == 1  # same site reuses the open baton
    monkeypatch.setattr("sys.argv", ["agent-baton", "back"])
    assert cli.main() == 0
    started["thread"].join(5)
    capsys.readouterr()
    monkeypatch.setattr("sys.argv", ["agent-baton", "wait"])
    assert cli.main() == 0 and "returned" in capsys.readouterr().out


def test_pass_refuses_denied_sites_and_reports_unreached_human(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["agent-baton", "pass", "my.1password.com"])
    with pytest.raises(SystemExit, match="never-browse"):
        cli.main()
    threads = []

    def fake_popen(cmd, **_):
        threads.append(threading.Thread(target=serve.serve, args=(cmd[-1],), daemon=True))
        threads[-1].start()

    monkeypatch.setattr(cli.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(notify, "notify", lambda *a, **k: ["toast-failed:FileNotFoundError"])
    monkeypatch.setattr("sys.argv", ["agent-baton", "pass", "github.com"])
    assert cli.main() == 0 and "No channel reached the human" in capsys.readouterr().out
    assert core.held()  # still held: the human can run `agent-baton back`
    core.resolve(core.held()[0]["id"], "cancelled")
    threads[0].join(5)  # a daemon left looping would outlive this test's tmp dir


def test_each_open_baton_gets_its_own_phone_port_then_falls_back_to_local(monkeypatch):
    import socket

    sent = []
    monkeypatch.setattr(
        notify, "notify", lambda baton, link, cfg, public=None: sent.append((link, cfg["ntfy"], public)) or []
    )
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    core.CONFIG.write_text(
        f'port = {port}\nslots = 2\nurl = "http://box.example"\nntfy = "https://ntfy.example/t"'
    )
    batons = [core.create(site, "", "Codex", 600) for site in ("a.com", "b.com", "c.com")]
    first, second, third = batons
    threads = [threading.Thread(target=serve.serve, args=(b["id"],), daemon=True) for b in batons]
    for opened, thread in enumerate(threads, start=1):
        thread.start()
        for _ in range(100):  # one at a time, so each really holds its port
            if len(sent) == opened:
                break
            threading.Event().wait(0.05)
    assert len(sent) == 3
    assert sent[0][0].startswith(f"http://localhost:{port}/") and sent[0][2].startswith("http://box.example/")
    assert sent[1][0].startswith(f"http://localhost:{port + 1}/") and sent[1][2].startswith(
        "http://box.example:81/"
    )
    assert sent[2][1] == "" and sent[2][2] is None  # slots exhausted: local-only, no phone alert
    for b in batons:
        core.resolve(b["id"], "cancelled")
    for thread in threads:
        thread.join(5)


def test_toast_xml_escapes_agent_text_and_survives_powershell_quoting():
    baton = {"id": "ab12", "kind": "login", "by": "Codex", "site": "a.com", "reason": "\"><evil/> it's 'x'"}
    script = notify.toast_script(baton, "http://localhost:1/tok")
    assert "$toast.Tag = 'ab12'" in script  # what dismiss() removes later
    assert "AppUserModelId\\agent-baton" in script  # our own name and icon, not "Windows PowerShell"
    assert base64.b64decode(notify.ICON).startswith(b"\x89PNG")
    assert "<evil/>" not in script and "&lt;evil/&gt;" in script
    xml = script.split("LoadXml('", 1)[1].split("')\n", 1)[0]
    assert "'" not in xml.replace("''", "")  # every apostrophe doubled for the PS string
    assert "http://localhost:1/tok/back" in xml


def test_ntfy_carries_click_and_done_actions(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        notify.urllib.request,
        "urlopen",
        lambda request, timeout: (
            seen.update(h=dict(request.header_items()), url=request.full_url, data=request.data)
            or io.BytesIO()
        ),
    )
    baton = {"kind": "login", "by": "Claude", "site": "a.com", "reason": "reading the secret plan"}
    notify.ntfy("https://ntfy.example/topic", baton, "https://box.ts.net/tok")
    assert seen["url"] == "https://ntfy.example/topic"
    assert seen["h"]["Title"] == "Claude needs you"
    assert "a.com" not in str(seen) and "secret plan" not in str(seen)  # details stay on the page
    assert seen["h"]["Click"] == "https://box.ts.net/tok"
    assert "https://box.ts.net/tok/back" in seen["h"]["Actions"]
    assert seen["h"]["Actions"].count(",") == 4  # "view, label, url" twice; a comma in a label is rejected


def post(url, **form):
    request = urllib.request.Request(
        url, data=urllib.parse.urlencode(form, doseq=True).encode(), method="POST"
    )

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    try:
        return urllib.request.build_opener(NoRedirect).open(request, timeout=5).status
    except urllib.error.HTTPError as error:
        return error.code


def run_baton(argv):
    return core.create(
        "sh", "", "Claude", 600, kind="run", argv=argv, command=" ".join(argv), cwd=str(core.BATONS)
    )


def test_command_waits_for_approval_and_a_typed_password_never_reaches_the_agent(monkeypatch, capsys):
    secret = "hunter2-dummy"
    script = 'printf "Password: " >/dev/tty; read -rs pw </dev/tty; echo "got:${#pw}"; exit 3'
    baton = run_baton(["bash", "-c", script])  # dash's `read` has no -s
    link, thread = open_serve(monkeypatch, baton["id"])
    base = link.rsplit("/", 1)[0]
    assert "sh -c" in get(link)[1] and "Run it" in get(link)[1]
    assert not core.output_path(baton["id"], "out").exists()  # nothing ran before the human said so
    assert post(f"{base}/not-the-token/run") == 404
    assert post(f"{link}/frobnicate") == 404
    assert core.load(baton["id"])["status"] == "held" and not core.output_path(baton["id"], "out").exists()
    assert post(f"{link}/run") == 303
    assert baton["id"] in dismissed  # approved: the toast comes down
    assert core.load(baton["id"])["expires"] >= baton["expires"]  # the limit restarts at Run
    for _ in range(100):  # the page shows the command's own prompt, which only the human sees
        if "Password:" in get(f"{link}/state")[1]:  # not the page: it also shows the command text
            break
        threading.Event().wait(0.05)
    assert "Password:" in get(f"{link}/state")[1]
    assert post(f"{link}/type", secret=secret) == 303
    thread.join(10)
    done = core.load(baton["id"])
    assert done["status"] == "returned" and done["exit"] == 3
    monkeypatch.setattr("sys.argv", ["agent-baton", "wait", baton["id"]])
    assert cli.main() == 1
    result = capsys.readouterr().out
    assert "exited 3" in result and "got:13" in result
    everything = (
        result + json.dumps(done) + "".join(p.read_text() for p in core.BATONS.iterdir() if p.is_file())
    )
    assert secret not in everything  # not in what the agent sees, nor anywhere on disk


def test_command_decline_and_expiry_never_run_or_stop_it(monkeypatch):
    baton = run_baton(["sh", "-c", "echo ran"])
    link, thread = open_serve(monkeypatch, baton["id"])
    assert post(f"{link}/decline") == 303
    thread.join(5)
    assert (
        core.load(baton["id"])["status"] == "cancelled" and not core.output_path(baton["id"], "out").exists()
    )
    slow = run_baton(["sh", "-c", "sleep 30"])
    link, thread = open_serve(monkeypatch, slow["id"])
    assert post(f"{link}/run") == 303
    expiring = core.load(slow["id"])
    expiring["expires"] = core.now() - 1
    core.save(expiring)
    thread.join(10)
    assert not thread.is_alive() and core.load(slow["id"])["status"] == "expired"


def test_run_cli_and_login_guard_independence(monkeypatch, capsys):
    monkeypatch.setattr(cli.subprocess, "Popen", lambda cmd, **_: None)
    monkeypatch.setattr(cli, "reached", lambda baton: {**baton, "notified": ["toast"]})
    monkeypatch.setattr(
        "sys.argv", ["agent-baton", "run", "--reason", "install", "--", "sudo", "install", "x"]
    )
    assert cli.main() == 0
    assert "sudo install x" in capsys.readouterr().out
    assert core.held("run") and not core.held("login")
    assert verdict("mcp__claude-in-chrome__computer") is None  # a pending command never blinds the browser
    monkeypatch.setattr("sys.argv", ["agent-baton", "run"])
    with pytest.raises(SystemExit, match="usage"):
        cli.main()


def test_ask_wait_says_the_answers_are_gone_rather_than_that_nobody_answered(monkeypatch, capsys):
    baton = core.create("Sign in", "", "Codex", 600, kind="ask", fields=[], answered=True, hold=600)
    core.resolve(baton["id"], "returned")
    monkeypatch.setattr("sys.argv", ["agent-baton", "wait", baton["id"]])
    assert cli.main() == 0
    assert "forgotten" in capsys.readouterr().out
    cancelled = core.create("Sign in", "", "Codex", 600, kind="ask", fields=[], answered=False, hold=600)
    core.resolve(cancelled["id"], "cancelled")
    monkeypatch.setattr("sys.argv", ["agent-baton", "wait", cancelled["id"]])
    assert cli.main() == 1
    assert "declined" in capsys.readouterr().out


def test_doctor_names_each_gap_and_passes_when_there_is_none(monkeypatch, capsys, tmp_path):
    (tmp_path / "config.toml").write_text(
        'port = 47600\nslots = 2\nurl = "http://100.1.2.3"\nntfy = "https://ntfy.sh/t"\n', encoding="utf-8"
    )
    hook = tmp_path / "hooks.json"
    monkeypatch.setattr(doctor, "HOOKS", (hook,))
    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/bin/" + name)
    monkeypatch.setattr(doctor, "libs_load", lambda: True)
    monkeypatch.setattr(doctor, "forwards", lambda: {"80": "127.0.0.1:47600"})
    assert doctor.main() == 1
    out = capsys.readouterr().out
    assert "no `agent-baton guard`" in out
    assert "tailscale serve --bg --tcp=81 tcp://127.0.0.1:47601" in out and "--tcp=80" not in out
    hook.write_text('{"command": "agent-baton guard"}', encoding="utf-8")
    monkeypatch.setattr(doctor, "forwards", lambda: {"80": "127.0.0.1:47600", "81": "127.0.0.1:47601"})
    assert doctor.main() == 0


@pytest.mark.parametrize(
    "options, reply",
    [([], {"answer": "Keep it local 🦊"}), (["Local", "Everywhere"], {"choice": "1", "answer": ""})],
)
def test_question_cli_returns_ordinary_answers_without_typing_or_blocking(
    monkeypatch, capsys, options, reply
):
    threads = []
    links = []

    def fake_popen(cmd, **_):
        thread = threading.Thread(target=serve.serve, args=(cmd[-1],), daemon=True)
        threads.append(thread)
        thread.start()

    monkeypatch.setattr(cli.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        notify, "notify", lambda baton, link, cfg, public=None: links.append(link) or ["test"]
    )
    monkeypatch.setenv("AGENT_BATON_BY", "Another harness")
    argv = ["agent-baton", "question", "Scope <b>of work</b>?", "--reason", "Choose <carefully>"]
    for option in options:
        argv.extend(["--option", option])
    monkeypatch.setattr("sys.argv", argv)
    assert cli.main() == 0
    baton = core.held("question")[0]
    assert baton["by"] == "Another harness"
    assert "question with the human" in capsys.readouterr().out
    assert core.path_of(baton["id"]).stat().st_mode & 0o777 == 0o600
    assert verdict("mcp__playwright__click") is None and not asking_sock(baton["id"]).exists()
    page = get(links[0])[1]
    assert "Scope &lt;b&gt;of work&lt;/b&gt;?" in page and "Choose &lt;carefully&gt;" in page
    assert "Do not enter passwords" in page and "checked" not in page
    monkeypatch.setattr("sys.argv", ["agent-baton", "wait", baton["id"], "--timeout", "0"])
    assert cli.main() == cli.STILL_HELD
    capsys.readouterr()
    assert post(f"{links[0]}/answer", **reply) == 200
    threads[0].join(5)
    assert not threads[0].is_alive()
    assert cli.main() == 0
    result = json.loads(capsys.readouterr().out)
    expected = options[1] if options else reply["answer"]
    assert result == {"id": baton["id"], "question": baton["question"], "answer": expected}
    assert dismissed == [baton["id"]]


@pytest.mark.parametrize(
    "prompt, options, ttl",
    [
        ("", [], 600),
        (" " * 3, [], 600),
        ("q" * 2001, [], 600),
        ("Q?", ["same", "same"], 600),
        ("Q?", [" "], 600),
        ("Q?", ["x" * 301], 600),
        ("Q?", list(map(str, range(11))), 600),
        ("Q?", [], 0),
        ("Q?", [], -1),
        ("Q?", [], True),
        ("Q?", [], 1.5),
    ],
)
def test_question_rejects_invalid_definitions_without_creating_state(prompt, options, ttl):
    with pytest.raises(ValueError):
        question.create(prompt, options, "", "Any harness", ttl)
    assert core.all_batons() == []


@pytest.mark.parametrize(
    "form",
    [
        {},
        {"choice": "42"},
        {"choice": "00"},
        {"choice": "other", "answer": " "},
        {"choice": "0", "answer": "ambiguous"},
        {"choice": ["0", "1"]},
        {"choice": "0", "unexpected": "x"},
        {"choice": "other", "answer": "a" * 2001},
    ],
)
def test_question_rejects_invalid_or_ambiguous_answers(monkeypatch, form):
    baton = question.create("Scope?", ["Local", "Everywhere"], "", "Codex", 600)
    link, thread = open_serve(monkeypatch, baton["id"])
    try:
        assert post(f"{link}/answer", **form) == 400
        assert core.load(baton["id"])["status"] == "held"
    finally:
        question.complete(baton["id"])
        thread.join(5)


def test_question_accepts_other_and_full_unicode_text(monkeypatch, capsys):
    baton = question.create("Scope?", ["Local", "Everywhere"], "", "Codex", 600)
    link, thread = open_serve(monkeypatch, baton["id"])
    answer = "🦊" * question.MAX_ANSWER  # percent-encoded UTF-8 is larger than the old secret form limit
    assert post(f"{link}/answer", choice="other", answer=answer) == 200
    thread.join(5)
    monkeypatch.setattr("sys.argv", ["agent-baton", "wait", baton["id"], "--timeout", "0"])
    assert cli.main() == 0 and json.loads(capsys.readouterr().out)["answer"] == answer


def test_select_many_returns_a_list_in_option_order_and_accepts_other(monkeypatch, capsys):
    baton = question.create("Which checks?", ["Linux", "Windows"], "", "Codex", 600, multiple=True)
    link, thread = open_serve(monkeypatch, baton["id"])
    page = get(link)[1]
    assert "Choose one or more" in page and page.count("type=checkbox") == 3
    assert "checked" not in page and "type=radio" not in page
    assert post(f"{link}/answer", choice=["0", "0"]) == 400
    assert post(f"{link}/answer", choice=["0", "other"], answer="Linux") == 400
    assert post(f"{link}/answer", choice=["1", "other", "0"], answer="Phone") == 200
    thread.join(5)
    monkeypatch.setattr("sys.argv", ["agent-baton", "wait", baton["id"], "--timeout", "0"])
    assert cli.main() == 0
    assert json.loads(capsys.readouterr().out)["answer"] == ["Linux", "Windows", "Phone"]
    with pytest.raises(ValueError, match="need options"):
        question.create("Which?", [], "", "Codex", 600, multiple=True)


def test_question_withdrawal_and_first_answer_win_across_processes(monkeypatch, capsys):
    import multiprocessing
    from concurrent.futures import ProcessPoolExecutor

    baton = question.create("Scope?", [], "", "Codex", 600)
    link, thread = open_serve(monkeypatch, baton["id"])
    monkeypatch.setattr("sys.argv", ["agent-baton", "withdraw", baton["id"]])
    assert cli.main() == 0 and "withdrawn" in capsys.readouterr().out
    thread.join(5)
    assert not thread.is_alive() and "answer" not in core.load(baton["id"])
    assert question.complete(baton["id"], {"answer": ["too late"]})["status"] == "withdrawn"
    monkeypatch.setattr("sys.argv", ["agent-baton", "wait", baton["id"], "--timeout", "0"])
    assert cli.main() == 1 and "not a human answer or approval" in capsys.readouterr().out
    other = question.create("Scope?", [], "", "Codex", 600)
    with ProcessPoolExecutor(max_workers=2, mp_context=multiprocessing.get_context("fork")) as pool:
        futures = [
            pool.submit(question.complete, other["id"], form)
            for form in ({"answer": ["first"]}, {"answer": ["second"]}, None)
        ]
        results = [future.result(timeout=5) for future in futures]
    assert all(result == results[0] for result in results)  # one immutable outcome, never a late overwrite


@pytest.mark.parametrize("outcome", ["decline", "expiry"])
def test_question_decline_and_expiry_are_not_answers(monkeypatch, capsys, outcome):
    baton = question.create("Scope?", [], "", "Codex", 600)
    link, thread = open_serve(monkeypatch, baton["id"])
    if outcome == "decline":
        assert post(f"{link}/decline") == 200
    else:
        core.save({**core.load(baton["id"]), "expires": core.now() - 1})
    thread.join(5)
    monkeypatch.setattr("sys.argv", ["agent-baton", "wait", baton["id"], "--timeout", "0"])
    assert cli.main() == 1 and "answer" not in core.load(baton["id"])
    assert "Do not retry" in capsys.readouterr().out


def test_question_is_separate_from_secret_handoffs_and_phone_pushes(monkeypatch, capsys):
    baton = question.create("Private project choice?", ["A", "B"], "private reason", "Claude", 600)
    assert notify.buttons(baton, "http://localhost/tok") == [("Open the form", "http://localhost/tok")]
    assert "sign in" not in notify.headline(baton)
    script = notify.toast_script(baton, "http://localhost/tok")
    assert "private reason" not in script and "Private project choice" not in script
    assert "/back" not in script
    monkeypatch.setattr("sys.argv", ["agent-baton", "back", baton["id"]])
    with pytest.raises(SystemExit, match="only for logins"):
        cli.main()
    login = core.create("example.com", "", "Codex", 600)
    monkeypatch.setattr("sys.argv", ["agent-baton", "withdraw", login["id"]])
    with pytest.raises(SystemExit, match="no baton matches"):
        cli.main()
    with pytest.raises(ValueError, match="only ordinary questions"):
        question.complete(login["id"])
    assert core.load(login["id"])["status"] == "held"
    cli.reached({**baton, "notified": ["toast-failed:OSError"]})
    warning = capsys.readouterr().out
    assert "original harness question pending" in warning and "agent-baton back" not in warning


def test_cli_form_collects_typed_answers_and_omits_unanswered_optional_fields(monkeypatch, capsys):
    opened = []

    def launch(baton):
        opened.append(open_serve(monkeypatch, baton["id"]))
        return baton

    monkeypatch.setattr(cli, "launch", launch)
    example = Path(__file__).parents[1] / "examples/review-form.json"
    monkeypatch.setattr("sys.argv", ["agent-baton", "form", str(example)])
    assert cli.main() == 0
    capsys.readouterr()
    baton = core.held("question")[0]
    link, thread = opened[0]
    page = get(link)[1]
    assert 'name="scope.choice"' in page and 'name="platforms.choice"' in page and "(optional)" in page
    assert post(f"{link}/answer", **{"scope.choice": "0"}) == 400  # missing required platforms
    fields = {"scope.choice": "0", "platforms.choice": ["1", "0"], "notes.answer": ""}
    assert post(f"{link}/answer", **fields, **{"unknown.answer": "x"}) == 400
    assert post(f"{link}/answer", **fields) == 200
    thread.join(5)
    monkeypatch.setattr("sys.argv", ["agent-baton", "wait", baton["id"], "--timeout", "0"])
    assert cli.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result == {
        "id": baton["id"],
        "title": "Review choices",
        "answers": {"scope": "This project", "platforms": ["Linux / WSL", "Windows"]},
    }


@pytest.mark.parametrize(
    "definition",
    [
        "[]",
        '{"title":"x","title":"y","questions":[]}',
        '{"title":"x","questions":NaN}',
        '{"title":"x","questions":[],"html":"<b>no</b>"}',
        '{"title":"x","questions":[{"id":"a","type":"password","question":"Q?"}]}',
        '{"title":"x","questions":[{"id":"a","type":"text","question":"Q?","required":"false"}]}',
        '{"title":"x","questions":[{"id":"a","type":"text","question":"Q?","options":[]}]}',
        '{"title":"x","questions":[{"id":"a","type":"choice","question":"Q?"}]}',
        '{"title":"x","questions":[{"id":"bad.id","type":"text","question":"Q?"}]}',
        '{"title":"x","questions":[{"id":"a","type":"text","question":"Q?"},'
        '{"id":"a","type":"text","question":"Again?"}]}',
    ],
)
def test_form_rejects_ambiguous_or_unsupported_definitions(tmp_path, definition):
    path = tmp_path / "form.json"
    path.write_text(definition)
    with pytest.raises(ValueError):
        question.load_form(path)
    assert not core.all_batons()


def test_form_definition_size_is_bounded(tmp_path):
    path = tmp_path / "form.json"
    path.write_bytes(b" " * 65537)
    with pytest.raises(ValueError, match="64 KiB"):
        question.load_form(path)


@pytest.mark.parametrize(
    "body, length",
    [
        (b"answer=%FF", None),
        (b"answer=\xff", None),
        (b"", "-1"),
        (b"", "invalid"),
        (b"answer=one&answer=two", None),
    ],
)
def test_question_rejects_malformed_form_envelopes(monkeypatch, body, length):
    import http.client

    baton = question.create("Q?", [], "", "Codex", 600)
    link, thread = open_serve(monkeypatch, baton["id"])
    url = urllib.parse.urlsplit(link)
    connection = http.client.HTTPConnection(url.hostname, url.port, timeout=5)
    try:
        headers = {"Content-Length": length} if length is not None else {}
        connection.request("POST", f"{url.path}/answer", body, headers)
        response = connection.getresponse()
        assert response.status == 400
        response.read()
        assert core.load(baton["id"])["status"] == "held"
    finally:
        connection.close()
        question.complete(baton["id"])
        thread.join(5)


def test_session_identity_uses_conversation_ids_and_never_the_display_name(monkeypatch):
    monkeypatch.delenv("AGENT_BATON_SESSION")
    monkeypatch.setenv("CODEX_THREAD_ID", "thread-a")
    first = core.session()
    monkeypatch.setenv("AGENT_BATON_BY", "Same harness")
    assert core.session() == first
    monkeypatch.setenv("CODEX_THREAD_ID", "thread-b")
    assert core.session() != first
    monkeypatch.setenv("AGENT_BATON_SESSION", "thread-a")
    assert core.session() != first  # explicit owners have their own namespace
    monkeypatch.delenv("CODEX_THREAD_ID")
    assert core.session() == "explicit:thread-a"


def test_claude_code_session_is_picked_up_without_a_shared_namespace(monkeypatch):
    monkeypatch.delenv("AGENT_BATON_SESSION")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "same-id")
    claude = core.session()
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID")
    monkeypatch.setenv("CODEX_THREAD_ID", "same-id")
    assert core.session() != claude  # one id string in two harnesses is two owners
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "same-id")
    monkeypatch.setenv("AGENT_BATON_SESSION", "mine")
    assert core.session() == "explicit:mine"  # an explicit id still wins


def test_a_late_answer_is_never_overwritten_by_a_reader_that_saw_it_expire():
    baton = question.create("Scope?", [], "", "Codex", 600)
    stale = {**baton, "expires": core.now() - 1}  # read just before the answer landed
    question.complete(baton["id"], {"answer": ["Local"]})
    assert core.settle(stale)["status"] == "returned"
    assert core.read(baton["id"])["answer"] == "Local"


def test_until_done_waits_past_timeout_and_stops_at_expiry(monkeypatch, capsys):
    baton = question.create("Scope?", [], "", "Codex", 600)
    monkeypatch.setattr("sys.argv", ["agent-baton", "wait", baton["id"], "--timeout", "0"])
    assert cli.main() == cli.STILL_HELD
    capsys.readouterr()
    core.save({**baton, "expires": core.now() - 1})
    monkeypatch.setattr("sys.argv", ["agent-baton", "wait", baton["id"], "--until-done"])
    assert cli.main() == 1 and "expired" in capsys.readouterr().out


@pytest.mark.parametrize("command", [["question", "Q?"], ["pass", "example.com"], ["status"]])
def test_missing_session_identity_fails_closed_without_state(monkeypatch, capsys, command):
    monkeypatch.delenv("AGENT_BATON_SESSION")
    monkeypatch.setenv("CLAUDECODE", "1")  # a harness name/presence is not a unique session
    monkeypatch.setattr("sys.argv", ["agent-baton", *command])
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code != 0
    assert "no session identity" in capsys.readouterr().err + str(error.value.code)
    assert not core.BATONS.exists()


@pytest.mark.parametrize("owner", ["", " ", "two sessions", "trailing\n", "x" * 201])
def test_invalid_explicit_session_does_not_fall_back_to_another_owner(monkeypatch, owner):
    monkeypatch.setenv("CODEX_THREAD_ID", "thread-a")
    monkeypatch.setenv("AGENT_BATON_SESSION", owner)
    with pytest.raises(ValueError, match="AGENT_BATON_SESSION"):
        core.create("example.com", "", "Codex", 600)
    assert not core.BATONS.exists()


@pytest.mark.parametrize("kind", ["question", "ask", "run", "login"])
def test_explicit_and_default_selection_and_status_only_see_own_session(monkeypatch, capsys, kind):
    first = core.create("own.example", "", "Same harness", 600, kind=kind, fields=[], command="own")
    core.resolve(first["id"], "returned")
    monkeypatch.setenv("AGENT_BATON_SESSION", "other-session")
    other = core.create("other.example", "", "Same harness", 600, kind=kind, fields=[], command="other")
    monkeypatch.setenv("AGENT_BATON_SESSION", "test-session")
    assert cli.pick(None)["id"] == first["id"]
    assert cli.pick(first["id"])["id"] == first["id"]
    assert core.held() == []
    for ref in (other["id"], other["site"]):
        with pytest.raises(SystemExit, match="no baton matches"):
            cli.pick(ref)
    monkeypatch.setattr("sys.argv", ["agent-baton", "status"])
    assert cli.main() == 0
    output = capsys.readouterr().out
    assert first["id"] in output and other["id"] not in output and other["site"] not in output


def test_two_live_questions_cannot_consume_or_withdraw_each_others_replies(monkeypatch, capsys):
    first = question.create("Scope?", ["A", "B"], "", "Codex", 600)
    first_link, first_thread = open_serve(monkeypatch, first["id"])
    monkeypatch.setenv("AGENT_BATON_SESSION", "other-session")
    other = question.create("Scope?", ["A", "B"], "", "Codex", 600)
    other_link, other_thread = open_serve(monkeypatch, other["id"])
    try:
        monkeypatch.setenv("AGENT_BATON_SESSION", "test-session")
        monkeypatch.setattr("sys.argv", ["agent-baton", "withdraw", other["id"]])
        with pytest.raises(SystemExit, match="no baton matches"):
            cli.main()
        assert core.load(other["id"])["status"] == "held"
        other_token = urllib.parse.urlsplit(other_link).path
        first_url = urllib.parse.urlsplit(first_link)
        assert post(f"{first_url.scheme}://{first_url.netloc}{other_token}/answer", choice="0") == 404
        assert post(f"{other_link}/answer", choice="1") == 200
        other_thread.join(5)
        assert dismissed == [other["id"]] and first_thread.is_alive()
        monkeypatch.setattr("sys.argv", ["agent-baton", "wait", "--timeout", "0"])
        assert cli.main() == cli.STILL_HELD  # B's reply is ready, but A is still waiting
        assert "answer" not in capsys.readouterr().out
        monkeypatch.setattr("sys.argv", ["agent-baton", "withdraw", other["id"]])
        with pytest.raises(SystemExit, match="no baton matches"):
            cli.main()
        assert post(f"{first_link}/answer", choice="0") == 200
        first_thread.join(5)
        assert set(dismissed) == {first["id"], other["id"]}
        monkeypatch.setattr("sys.argv", ["agent-baton", "wait", other["id"], "--timeout", "0"])
        with pytest.raises(SystemExit, match="no baton matches"):
            cli.main()
        monkeypatch.setattr("sys.argv", ["agent-baton", "wait", "--timeout", "0"])
        assert cli.main() == 0
        assert json.loads(capsys.readouterr().out) == {"id": first["id"], "question": "Scope?", "answer": "A"}
        monkeypatch.setenv("AGENT_BATON_SESSION", "other-session")
        assert cli.main() == 0
        assert json.loads(capsys.readouterr().out) == {"id": other["id"], "question": "Scope?", "answer": "B"}
    finally:
        for baton, thread in ((first, first_thread), (other, other_thread)):
            question.complete(baton["id"])
            thread.join(5)


def test_secrets_are_never_typed_or_forgotten_from_another_session(monkeypatch, capsys):
    first = core.create("Sign in", "", "Codex", 600, kind="ask", answered=True, fields=[])
    monkeypatch.setenv("AGENT_BATON_SESSION", "other-session")
    other = core.create("Sign in", "", "Codex", 600, kind="ask", answered=True, fields=[])
    monkeypatch.setenv("AGENT_BATON_SESSION", "test-session")
    requests = []
    monkeypatch.setattr(
        cli.asking,
        "request",
        lambda baton_id, *args: requests.append(baton_id) or {"text": "typed", "code": 0},
    )
    monkeypatch.setattr("sys.argv", ["agent-baton", "type", "password"])
    assert cli.main() == 0 and requests == [first["id"]]
    capsys.readouterr()
    for argv in (["type", "password", "--id", other["id"]], ["forget", other["id"]]):
        monkeypatch.setattr("sys.argv", ["agent-baton", *argv])
        with pytest.raises(SystemExit, match="no baton matches"):
            cli.main()
    assert requests == [first["id"]] and core.load(other["id"])["status"] == "held"
    core.create("Sign in", "", "Codex", 600, kind="ask", answered=True, fields=[])
    monkeypatch.setattr("sys.argv", ["agent-baton", "type", "password"])
    with pytest.raises(SystemExit, match="several batons"):
        cli.main()  # even within one session, an ambiguous secret requires an explicit id


def test_same_site_login_is_only_reused_within_its_own_session(monkeypatch, capsys):
    core.create("example.com", "", "Codex", 600)
    monkeypatch.setenv("AGENT_BATON_SESSION", "other-session")
    started = []
    monkeypatch.setattr(cli, "launch", lambda baton: started.append(baton) or baton)
    monkeypatch.setattr(cli, "reached", lambda baton: {**baton, "notified": ["test"]})
    monkeypatch.setattr("sys.argv", ["agent-baton", "pass", "example.com"])
    assert cli.main() == 0 and len(started) == 1
    assert cli.main() == 0 and len(started) == 1
    assert len(core.all_batons()) == 1 and len(core.all_batons(all_sessions=True)) == 2


def test_old_unowned_requests_are_never_adopted_but_the_shared_screen_stays_private(monkeypatch):
    legacy = core.create("example.com", "", "Codex", 600)
    del legacy["session"]
    core.save(legacy)
    assert core.all_batons() == []
    with pytest.raises(SystemExit, match="no baton matches"):
        cli.pick(legacy["id"])
    monkeypatch.setenv("AGENT_BATON_SESSION", "other-session")
    assert run_guard(monkeypatch, {"tool_name": "mcp__playwright__screenshot"}) == 2
    core.resolve(legacy["id"], "returned")
    question.create("Scope?", [], "", "Codex", 600)
    monkeypatch.delenv("AGENT_BATON_SESSION")
    assert run_guard(monkeypatch, {"tool_name": "mcp__playwright__screenshot"}) == 0


def test_request_id_collision_cannot_replace_another_sessions_state(monkeypatch):
    first = core.create("example.com", "", "Codex", 600)
    monkeypatch.setenv("AGENT_BATON_SESSION", "other-session")
    ids = iter([first["id"], "a" * 16])
    monkeypatch.setattr(core.secrets, "token_hex", lambda size: next(ids) if size == 8 else "b" * (size * 2))
    other = core.create("example.com", "", "Codex", 600)
    assert len(first["id"]) == len(other["id"]) == 16 and first["id"] != other["id"]
    assert core.load(first["id"]) == first and core.load(other["id"]) == other


def test_simultaneous_question_notifications_keep_separate_tags_and_reply_links(monkeypatch):
    first = question.create("Scope?", ["A", "B"], "", "Codex", 600)
    monkeypatch.setenv("AGENT_BATON_SESSION", "other-session")
    other = question.create("Scope?", ["A", "B"], "", "Codex", 600)
    scripts, pushes = [], []
    monkeypatch.setattr(notify, "powershell", scripts.append)
    monkeypatch.setattr(
        notify.urllib.request, "urlopen", lambda request, timeout: pushes.append(request) or io.BytesIO()
    )
    for baton, port, token in ((first, 47600, "first-token"), (other, 47601, "other-token")):
        link = f"http://localhost:{port}/{token}"
        assert notify.notify(baton, link, {"ntfy": "https://ntfy.example/shared-topic"}) == ["toast", "ntfy"]
    assert f"$toast.Tag = '{first['id']}'" in scripts[0] and other["id"] not in scripts[0]
    assert f"$toast.Tag = '{other['id']}'" in scripts[1] and first["id"] not in scripts[1]
    first_push, other_push = (dict(request.header_items()) for request in pushes)
    assert pushes[0].full_url == pushes[1].full_url  # sharing a notification topic does not share a form
    assert first_push["Click"] == "http://localhost:47600/first-token"
    assert other_push["Click"] == "http://localhost:47601/other-token"
    assert "other-token" not in first_push["Actions"] and "first-token" not in other_push["Actions"]


def test_failed_creation_releases_its_reservation_without_touching_another_request(monkeypatch):
    first = core.create("example.com", "", "Codex", 600)
    monkeypatch.setenv("AGENT_BATON_SESSION", "other-session")

    def fail_save(baton):
        raise OSError("storage unavailable")

    monkeypatch.setattr(core, "save", fail_save)
    with pytest.raises(OSError, match="storage unavailable"):
        core.create("example.com", "", "Codex", 600)
    assert list(core.BATONS.glob("*.json")) == [core.path_of(first["id"])]
    assert core.load(first["id"]) == first

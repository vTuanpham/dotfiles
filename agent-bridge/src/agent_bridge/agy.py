import contextlib
import io
import json
import os
import select
import shutil
import signal
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .core import (
    MESSAGING_RULE,
    POLL,
    capped,
    confirm_steer,
    link,
    log,
    poll_steers,
    route_to_peers,
    runner_finished,
    runner_started,
    save,
    worker_env,
)

ACCOUNTS = Path.home() / ".agy-accounts"
TOKEN = Path(".gemini/antigravity-cli/antigravity-oauth-token")
READ_ALL = ["read_file(/)"]  # a directory target is recursive: reads anywhere, like a codex sandbox


def account_env(account):
    home = ACCOUNTS / account
    if not (home / TOKEN).is_file():
        raise RuntimeError(f"account {account!r} has no login: run `HOME={home} agy` in a terminal")
    return {**os.environ, "HOME": str(home)}


def build_home(job, state):
    real, home = Path.home(), Path(job) / "home"
    token = ACCOUNTS / state["account"] / TOKEN
    if not token.is_file():
        raise RuntimeError(
            f"account {state['account']!r} has no login: run `HOME={ACCOUNTS / state['account']} agy` "
            "in a terminal"
        )
    gem, cli = home / ".gemini", home / ".gemini" / "antigravity-cli"
    cli.mkdir(parents=True, exist_ok=True)
    home.chmod(0o700)
    for entry in real.iterdir():
        if entry.name not in (".gemini", ".agy-accounts"):
            link(entry, home / entry.name)
    for entry in (real / ".gemini").iterdir() if (real / ".gemini").is_dir() else ():
        if entry.name not in ("antigravity-cli", "config"):
            link(entry, gem / entry.name)
    # agy rewrites config/projects on every run, so it is copied; the rest of config stays shared
    (gem / "config").mkdir(exist_ok=True)
    for entry in (real / ".gemini" / "config").iterdir() if (real / ".gemini" / "config").is_dir() else ():
        if entry.name == "projects":
            shutil.copytree(entry, gem / "config" / entry.name, dirs_exist_ok=True)
        else:
            link(entry, gem / "config" / entry.name)
    link(token, cli / TOKEN.name)
    roots = state["writableRoots"]
    perms = (
        {
            "allow": [*(f"write_file({r})" for r in roots), "command(*)", *READ_ALL, *state.get("allow", [])],
            "deny": state.get("deny", []),
        }
        if state["sandbox"] == "workspace-write"
        else {
            "allow": [*READ_ALL, *state.get("allow", [])],
            "deny": ["write_file(*)", *state.get("deny", [])],
        }
    )
    (cli / "settings.json").write_text(
        json.dumps(
            {"colorScheme": "dark", "trustedWorkspaces": [state["cwd"]], "permissions": perms}, indent=2
        )
        + "\n",
        encoding="utf-8",
    )
    (cli / "settings.json").chmod(0o600)
    return home


def switch_account(job, state, account):
    token = ACCOUNTS / account / TOKEN
    if not token.is_file():
        raise RuntimeError(
            f"account {account!r} has no login: run `HOME={ACCOUNTS / account} agy` in a terminal"
        )
    link = Path(job) / "home" / TOKEN
    link.unlink(missing_ok=True)
    link.symlink_to(token)
    state["account"] = account


def process(ev, state, job, send, texts=None):
    texts = texts if texts is not None else {}
    kind = ev.get("event")
    body = ev.get(kind) if isinstance(ev.get(kind), dict) else {}
    if kind == "init":
        state["conversationId"] = ev.get("conversation_id") or state.get("conversationId", "")
        save(Path(job) / "state.json", state)
        log(
            job,
            "thread_started",
            conversationId=state["conversationId"],
            model=(ev.get("init") or {}).get("model"),
        )
    elif kind == "step_update":
        st = body.get("state")
        if body.get("step_type") == "agent_response":
            step = body.get("step_index")
            texts[step] = texts.get(step, "") + (body.get("text_delta") or "")
            if st == "DONE" and texts.get(step, "").strip():
                text = texts.pop(step).strip()
                urgent = text.upper().startswith("URGENT:")
                routed = text[7:].lstrip() if urgent else text
                log(
                    job,
                    "message",
                    level="urgent" if urgent else "info",
                    text=routed,
                )
                route_to_peers(job, routed)
        elif body.get("step_type") == "tool":
            params = (body.get("tool_info") or {}).get("parameters") or {}
            if st == "ACTIVE":
                log(
                    job,
                    "command_start",
                    tool=body.get("tool_name"),
                    command=params.get("CommandLine") or params,
                )
            elif st == "DONE":
                log(job, "command_end", tool=body.get("tool_name"))
    elif kind == "result":
        state["turnsDone"] = state.get("turnsDone", 0) + 1
        inflight = state.get("inflight")
        if inflight and state["turnsDone"] >= inflight.get("turnsSent", 0):
            confirm_steer(job, state)
        if state["turnsDone"] >= state.get("turnsSent", 0):
            state["activeTurnId"] = None
        denied = body.get("denied_actions") or []
        error = body.get("error") or (body.get("response") if body.get("status") != "SUCCESS" else None)
        log(
            job,
            "turn_completed",
            status=body.get("status"),
            error=error or None,
            usage=body.get("usage"),
            denied=denied or None,
        )
        denied_seen = state.get("deniedSeen", 0)
        new_denial = len(denied) > denied_seen
        state["deniedSeen"] = max(denied_seen, len(denied))
        if new_denial:
            log(job, "permission_denied", level="urgent", denied=denied)
            continues = state.get("autoContinues", 0)
            if continues < 3:
                state["autoContinues"] = continues + 1
                send(
                    "The runner auto-denied these actions (not in this job's allow list): "
                    + json.dumps(denied)
                    + ". Continue without them. If one is essential, finish everything else, "
                    "then send a message starting with 'URGENT:' that names the exact command "
                    "or path you need."
                )
        else:
            state["autoContinues"] = 0
        save(Path(job) / "state.json", state)


def run(job, state, path, prompt, resume=False):
    if "gpt-oss" in (state.get("model") or "").lower():
        raise RuntimeError(
            "GPT-OSS models are excluded; pick a Gemini or Claude model (see `models --backend agy`)"
        )
    if not resume:
        build_home(job, state)
    cmd = ["agy", "--input-format", "stream-json", "--output-format", "stream-json", "--sandbox"]
    for flag, key in (("--model", "model"), ("--effort", "effort"), ("--conversation", "conversationId")):
        if state.get(key):
            cmd += [flag, state[key]]
    cmd.append("-p=")
    err = (Path(job) / "agy.stderr.log").open("a", encoding="utf-8")
    proc = subprocess.Popen(
        capped(cmd),
        cwd=state["cwd"],
        env=worker_env(job, HOME=str(Path(job) / "home")),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=err,
        bufsize=0,
        start_new_session=True,
    )
    runner_path = Path(job) / "state.json"
    runner_started(state, runner_path)
    buf = b""
    texts = {}
    reason = "normal"

    def send(text):
        proc.stdin.write(
            (json.dumps({"event": "user", "message": {"role": "user", "content": text}}) + "\n").encode()
        )
        proc.stdin.flush()
        state["turnsSent"] = state.get("turnsSent", 0) + 1
        state["activeTurnId"] = f"turn-{state['turnsSent']}"
        save(path, state)

    try:
        if state.get("inflight"):
            poll_steers(job, send, state=state, defer=True, redeliver=True, turn_key="turnsSent")
        if prompt:
            send(prompt if resume else f"{MESSAGING_RULE}\n\n---\n\n{prompt}")
        while True:
            ready, _, _ = select.select([proc.stdout], [], [], POLL)
            if ready:
                data = os.read(proc.stdout.fileno(), 1 << 20)
                if not data:
                    if state.get("turnsDone", 0) < state.get("turnsSent", 0):
                        reason = "error"
                        raise RuntimeError(f"agy exited mid-turn (code {proc.poll()}); see agy.stderr.log")
                    return
                with (Path(job) / "stream.ndjson").open("ab") as stream:
                    stream.write(data)
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    try:
                        process(json.loads(line), state, job, send, texts)
                    except json.JSONDecodeError:
                        pass
            if (Path(job) / "interrupt").exists():
                (Path(job) / "interrupt").unlink()
                os.killpg(proc.pid, signal.SIGINT)
                log(job, "interrupt_sent")
            if (Path(job) / "stop").exists():
                (Path(job) / "stop").unlink()
                log(job, "stopped")
                reason = "stopped"
                os.killpg(proc.pid, signal.SIGTERM)
                return
            poll_steers(job, send, state=state, defer=True, turn_key="turnsSent")
            if state.get("turnsDone", 0) >= state.get("turnsSent", 0) and not list(
                (Path(job) / "steer").glob("[0-9]*.md")
            ):
                proc.stdin.close()
                proc.wait(timeout=60)
                return
    except Exception as exc:
        reason = "error"
        log(job, "error", message=str(exc))
        raise
    finally:
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    log(job, "error", message="agy process group did not exit after SIGKILL")
        state["activeTurnId"] = None
        log(job, "runner_exit", reason=reason, turnsDone=state.get("turnsDone", 0))
        runner_finished(state, path)
        err.close()


def tier(model):
    """(cost tier, quota bucket) inferred from the id, so new models need no table: Argon/Opus ≈ Sol/Astra,
    Sonnet ≈ our Sonnet, Flash ≈ Luna/Haiku. GPT-OSS is excluded by the user."""
    m = model.lower()
    bucket = "argon" if "argon" in m else "claude" if ("claude" in m or "gpt" in m) else "gemini"
    cost = "heavy" if ("argon" in m or "opus" in m) else "mid" if "sonnet" in m else "cheap"
    return cost, bucket


def models(account="a1"):
    out = subprocess.run(
        ["agy", "models"], env=account_env(account), capture_output=True, text=True, timeout=120
    ).stdout
    for line in out.splitlines():
        mid, _, label = line.partition("\t")
        if label and "gpt-oss" not in mid:
            print("\t".join((mid, "-", *tier(mid), label)))


def quota(account=None):
    if account is None:
        for home in sorted(ACCOUNTS.iterdir()):
            if home.is_dir() and (home / TOKEN).is_file():
                quota(home.name)
        return
    result = subprocess.run(
        ["agy", "--output-format", "json", "-p=/usage"],
        env=account_env(account),
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(ACCOUNTS / account),
    )
    out = json.loads(result.stdout)
    rows = []
    for line in out.get("result", out).get("response", "").splitlines():
        parts = line.split("\t")
        if len(parts) == 4 and parts[2].rstrip("%").isdigit():
            rows.append(
                {
                    "group": parts[0],
                    "limit": parts[1],
                    "remaining": int(parts[2].rstrip("%")),
                    "resets": parts[3],
                }
            )
    if not rows:
        raise RuntimeError(f"no quota rows for {account}: {result.stderr.strip()[:200]}")
    from .core import save, stamp

    save(ACCOUNTS / account / "quota.json", {"account": account, "at": stamp(), "rows": rows})
    for q in rows:
        print(f"{account}\t{q['group']}\t{q['limit']}\t{q['remaining']}%\t{q['resets']}")


def fallback(job, state, state_path):
    if os.environ.get("AGENT_BRIDGE_AGY_FALLBACK") == "0":
        return
    bucket = tier(state.get("model") or "")[1]
    cooldowns = state.get("agyFallbackCooldowns", {})

    def quota_cache(account_dir):
        try:
            data = json.loads((account_dir / "quota.json").read_text())
            cached_at = datetime.fromisoformat(data["at"])
            if cached_at.tzinfo is None:
                raise ValueError("timezone required for cached quota")
            age = (datetime.now(timezone.utc) - cached_at.astimezone(timezone.utc)).total_seconds()
            if age > 600:
                raise ValueError("stale quota")
        except (OSError, ValueError, KeyError, TypeError):
            with contextlib.redirect_stdout(io.StringIO()):
                quota(account_dir.name)
            data = json.loads((account_dir / "quota.json").read_text())
        return data["rows"]

    while True:
        completed = []
        try:
            for line in (Path(job) / "live.jsonl").read_text(encoding="utf-8").splitlines():
                event = json.loads(line)
                if event.get("kind") == "turn_completed":
                    completed.append(event)
        except (OSError, json.JSONDecodeError):
            return
        error = str(completed[-1].get("error", "")) if completed else ""
        if (
            "quota" not in error.casefold()
            or "reach" not in error.casefold()
            or state.get("agyFallbackEvent") == len(completed)
        ):
            return
        state["agyFallbackEvent"] = len(completed)
        save(state_path, state)
        previous = state.get("account")
        try:
            current_rows = quota_cache(ACCOUNTS / str(previous))
            current_row = next((row for row in current_rows if bucket in row["group"].casefold()), {})
        except (OSError, ValueError, KeyError, TypeError):
            current_row = {}
        reset = current_row.get("resets") or error
        cooldowns[previous] = reset
        for account_dir in sorted(ACCOUNTS.iterdir()):
            account = account_dir.name
            if account == previous or not (account_dir / TOKEN).is_file():
                continue
            try:
                rows = quota_cache(account_dir)
            except Exception as exc:
                log(job, "account_quota_unavailable", account=account, message=str(exc))
                continue
            until = cooldowns.get(account)
            if until:
                try:
                    expires = datetime.fromisoformat(until)
                    if expires.tzinfo is None or expires.astimezone(timezone.utc) > datetime.now(
                        timezone.utc
                    ):
                        continue
                except ValueError:
                    continue
            row = next((row for row in rows if bucket in row["group"].casefold()), None)
            if row and int(row["remaining"]) > 0:
                switch_account(job, state, account)
                state["agyFallbackCooldowns"] = cooldowns
                save(state_path, state)
                log(
                    job,
                    "account_switched",
                    level="urgent",
                    **{"from": previous, "to": account, "reset": reset},
                )
                run(job, state, state_path, "Continue where you left off.", resume=True)
                break
        else:
            state["agyFallbackCooldowns"] = cooldowns
            save(state_path, state)
            return

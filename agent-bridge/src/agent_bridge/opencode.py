"""OpenCode CLI backend, confined by bubblewrap because OpenCode has no filesystem sandbox."""

import json
import os
import select
import shutil
import signal
import stat
import subprocess
from pathlib import Path

from .core import (
    MESSAGING_RULE,
    POLL,
    REDELIVERED,
    capped,
    command_env,
    confirm_steer,
    log,
    route_to_peers,
    runner_finished,
    runner_started,
    save,
    worker_env,
)
from .heavy import prepare as heavy_directory

DECLINED = "The user declined this tool call"  # OpenCode's auto-reject; it then aborts the turn
# The only free-tier models OpenCode documents as zero-retention and never trained on. Any other free model
# may log or train on prompts, so the bridge refuses it. Refresh this list from OpenCode's model docs.
ZDR_FREE = (
    "opencode/glm-5.3-flash-free",
    "opencode/deepseek-v4.1-flash-free",
    "opencode/minimax-m3.1-flash-free",
)


def logged_free(model):
    """A free-tier model that is not on the zero-retention list (the empty model falls back to one)."""
    free = not model or (
        model.startswith("opencode/") and ("free" in model or model == "opencode/big-pickle")
    )
    return free and model not in ZDR_FREE


def binary():
    return shutil.which("opencode") or str(Path.home() / ".opencode/bin/opencode")


def command(state, job, prompt, resume=False):
    if not shutil.which("bwrap"):
        raise RuntimeError("bwrap is required for opencode; refusing to run unconfined")
    model = state.get("model") or ""
    if logged_free(model):
        raise RuntimeError(
            f"{model or 'no --model'}: the free tier is limited to zero-retention models; "
            f"pass one of {', '.join(ZDR_FREE)}"
        )
    if state.get("effort"):  # OpenCode spells effort as a model variant: provider/model#variant
        if not model or "#" in model:
            raise RuntimeError("--effort needs --model without a #variant")
        model += "#" + state["effort"]
    cmd = [binary(), "run", "--standalone", "--format", "json"]
    if model:
        cmd += ["-m", model]
    if state.get("sessionId"):
        cmd += ["--session", state["sessionId"]]
    cmd += ["--title", state["title"]]
    env = worker_env(job)
    for key in list(env):
        if key in {"OPENCODE_CONFIG", "OPENCODE_CONFIG_DIR"} or key.startswith(
            ("OPENCODE_SERVER", "OPENCODE_PASSWORD")
        ):
            del env[key]
    # bwrap confines writes; OpenCode's own outside-cwd check would otherwise reject reads anywhere and
    # writes to writable roots (headless "ask" means reject)
    permission = {"external_directory": {"*": "allow"}}
    if state["sandbox"] == "read-only":
        permission.update(edit="deny", bash="deny", webfetch="deny", websearch="deny")
    env["OPENCODE_CONFIG_CONTENT"] = json.dumps({"permission": permission})

    writable = []
    if state["sandbox"] == "workspace-write":
        writable = list(state["writableRoots"])
    home = Path(job) / "home"
    data, state_dir, cache = (home / name for name in ("data", "state", "cache"))
    for path in (data / "opencode", state_dir / "opencode", cache / "opencode"):
        path.mkdir(parents=True, exist_ok=True)
    home.chmod(0o700)
    shared = Path.home()
    auth = shared / ".local/share/opencode/auth.json"
    private_auth = data / "opencode/auth.json"
    if auth.is_file():
        shutil.copyfile(auth, private_auth)
        private_auth.chmod(stat.S_IRUSR | stat.S_IWUSR)
    else:
        private_auth.unlink(missing_ok=True)
    models = shared / ".cache/opencode/models.json"
    if models.is_file():
        shutil.copyfile(models, cache / "opencode/models.json")
    else:
        (cache / "opencode/models.json").unlink(missing_ok=True)
    cache_mounts = []
    for name in ("bin", "node_modules", "packages", "package.json"):
        source = shared / ".cache/opencode" / name
        if source.exists():
            target = cache / "opencode" / name
            if source.is_dir():
                target.mkdir(exist_ok=True)
            else:
                target.touch(exist_ok=True)
            cache_mounts.append((source, target))
    args = [
        "bwrap",
        "--ro-bind",
        "/",
        "/",
        "--dev",
        "/dev",
        "--proc",
        "/proc",
        "--tmpfs",
        "/tmp",
        "--die-with-parent",
        "--ro-bind",  # the fresh /tmp would otherwise hide a read-only cwd under /tmp
        state["cwd"],
        state["cwd"],
    ]
    # later mounts cover earlier ones: the read-only job root first, so writable roots inside it stay writable
    args += ["--ro-bind", str(job), str(job), "--bind", str(home), str(home)]
    for path in dict.fromkeys(writable):
        args += ["--bind", path, path]
    if state["sandbox"] == "workspace-write":
        shared_heavy = str(heavy_directory())
        args += ["--bind", shared_heavy, shared_heavy]
    for source, target in cache_mounts:
        args += ["--ro-bind", str(source), str(target)]
    env.update(
        XDG_DATA_HOME=str(data),
        XDG_STATE_HOME=str(state_dir),
        XDG_CACHE_HOME=str(cache),
    )
    args += ["--chdir", state["cwd"], "--"]
    args += cmd
    return args, env


def process(event, state, job, turn=None):
    turn = turn if turn is not None else {"denied": [], "errors": [], "finished": False, "session": False}
    kind = event.get("type")
    part = event.get("part") or {}
    sid = event.get("sessionID")
    if sid and sid != state.get("sessionId"):
        state["sessionId"] = sid
        save(Path(job) / "state.json", state)
        log(job, "thread_started", sessionId=sid, model=state.get("model"))
    if sid:
        turn["session"] = True
    if kind == "text":
        text = (part.get("text") or "").strip()
        if text:
            turn["finished"] = True  # some provider routes emit no step events, only the reply
            urgent = text.lstrip().upper().startswith("URGENT:")
            routed = text.lstrip()[7:].lstrip() if urgent else text
            log(job, "message", level="urgent" if urgent else "info", text=routed)
            route_to_peers(job, routed)
    elif kind == "tool_use":
        tool = part.get("tool") or "tool"
        data = part.get("state") or {}
        inp = data.get("input") or {}
        log(job, "command_start", tool=tool, command=inp.get("command") or inp or data.get("title"))
        log(
            job,
            "command_end",
            tool=tool,
            status=data.get("status"),
            output=data.get("output")[:2000] if isinstance(data.get("output"), str) else data.get("output"),
            error=data.get("error"),
        )
        if data.get("status") == "error" and data.get("error") == DECLINED:
            turn["denied"].append(inp.get("command") or inp or tool)
    elif kind == "error":
        error = event.get("error") or {}
        if error.get("type") == "aborted" and turn["denied"]:
            return
        turn["errors"].append(error)
        log(job, "error", message=error.get("message") or json.dumps(error))
    elif kind == "step_finish":  # one per model step; the turn ends when the process exits
        turn["finished"] = True
        log(
            job,
            "step_finished",
            reason=part.get("reason"),
            usage=part.get("tokens"),
            cost=part.get("cost"),
        )


def run(job, state, path, prompt, resume=False):
    if not prompt and not list((Path(job) / "steer").glob("[0-9]*.md")):
        return
    runner_started(state, path)
    reason, turn = "normal", 0
    try:
        followup = f"{MESSAGING_RULE}\n\n---\n\n{prompt}" if prompt and not resume else prompt
        inflight = state.get("inflight")
        if inflight:
            steer = Path(job) / "steer" / inflight["file"]
            if not steer.exists() and (steer.parent / "sent" / steer.name).exists():
                confirm_steer(job, state)
                inflight = None
        pending = (
            f"{REDELIVERED}\n{(Path(job) / 'steer' / inflight['file']).read_text(encoding='utf-8').strip()}"
            if inflight
            else followup
        )
        if not inflight:
            followup = ""
        if inflight:
            log(job, "steer_redelivered", file=inflight["file"])
        pending_steer = inflight
        while pending or list((Path(job) / "steer").glob("[0-9]*.md")):
            if not pending:
                steer = next(iter(sorted((Path(job) / "steer").glob("[0-9]*.md"))))
                pending = steer.read_text(encoding="utf-8").strip()
                state["inflight"] = {"id": f"steer-{steer.stem}", "file": steer.name}
                save(path, state)
                pending_steer = state["inflight"]
            continuing = turn > 0 or resume
            if continuing and not state.get("sessionId"):
                raise RuntimeError("OpenCode session ID is missing; refusing to start a new session")
            cmd, env = command(state, job, pending, resume=continuing)
            stderr_path = Path(job) / "opencode.stderr.log"
            stderr_file = stderr_path.open("ab")
            proc = None
            try:
                proc = subprocess.Popen(
                    capped(cmd, state),
                    cwd=state["cwd"],
                    env=env,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=stderr_file,
                    bufsize=0,
                    start_new_session=True,
                )
                proc.stdin.write(pending.encode())
                proc.stdin.close()
                state["activeTurnId"] = f"turn-{turn + 1}"
                log(job, "turn_started", turnId=state["activeTurnId"])
                save(path, state)
                buf, interrupted = b"", False
                turn_data = {"denied": [], "errors": [], "finished": False, "session": False}
                while True:
                    ready, _, _ = select.select([proc.stdout], [], [], POLL)
                    if ready:
                        data = os.read(proc.stdout.fileno(), 1 << 20)
                        if not data:
                            break
                        with (Path(job) / "stream.ndjson").open("ab") as stream:
                            stream.write(data)
                        buf += data
                        while b"\n" in buf:
                            line, buf = buf.split(b"\n", 1)
                            try:
                                process(json.loads(line), state, job, turn_data)
                            except json.JSONDecodeError:
                                pass
                    if (Path(job) / "interrupt").exists():
                        (Path(job) / "interrupt").unlink()
                        try:
                            os.killpg(proc.pid, signal.SIGINT)
                        except ProcessLookupError:
                            pass
                        interrupted = True
                        log(job, "interrupt_sent")
                    if (Path(job) / "stop").exists():
                        (Path(job) / "stop").unlink()
                        log(job, "stopped")
                        reason = "stopped"
                        return
                code = proc.wait()
                if buf.strip():
                    try:
                        process(json.loads(buf), state, job, turn_data)
                    except json.JSONDecodeError:
                        pass
            finally:
                if proc is not None and proc.poll() is None:
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
                            log(job, "error", message="opencode process group did not exit after SIGKILL")
                stderr_file.close()
            denied = turn_data["denied"]
            if continuing and not turn_data["session"]:
                raise RuntimeError("OpenCode turn had no session ID; refusing to start a new session")
            if code and not interrupted and (not denied or turn_data["errors"]):
                tail = stderr_path.read_text(encoding="utf-8", errors="replace").strip()[-300:]
                raise RuntimeError(f"opencode exited with code {code}: {tail}")
            # exit 0 with no reply and no finished step (e.g. headless OpenCode cancelled a question form):
            # report it, but end normally so the session can be resumed (and lingering can answer).
            incomplete = not interrupted and not denied and not turn_data["finished"]
            if incomplete:
                log(job, "error", message="OpenCode turn ended without a reply")
            log(
                job,
                "turn_completed",
                status="interrupted"
                if interrupted
                else "denied"
                if denied
                else "incomplete"
                if incomplete
                else "completed",
            )
            if pending_steer:
                confirm_steer(job, state)
                pending_steer = None
            turn += 1
            state["activeTurnId"] = None
            pending = ""
            if followup and not pending:
                pending, followup = followup, ""
            if denied:
                log(job, "permission_denied", level="urgent", denied=denied)
                continues = state.get("autoContinues", 0)
                if continues < 3:
                    state["autoContinues"] = continues + 1
                    pending = (
                        "The runner auto-denied these actions (outside this job's permissions): "
                        + json.dumps(denied)
                        + ". Continue without them. If one is essential, finish everything else, "
                        "then send a message starting with 'URGENT:' that names the exact command "
                        "or path you need."
                    )
            else:
                state["autoContinues"] = 0
            save(path, state)
            queued = None if pending else next(iter(sorted((Path(job) / "steer").glob("[0-9]*.md"))), None)
            if queued:
                pending = queued.read_text(encoding="utf-8").strip()
                state["inflight"] = {"id": f"steer-{queued.stem}", "file": queued.name}
                save(path, state)
                pending_steer = state["inflight"]
            resume = True
    except Exception as exc:
        reason = "error"
        log(job, "error", message=str(exc))
        raise
    finally:
        state["activeTurnId"] = None
        log(job, "runner_exit", reason=reason, turnsDone=turn)
        runner_finished(state, path)


def models():
    result = subprocess.run([binary(), "models"], env=command_env(),
                            capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"opencode models exited with code {result.returncode}")
    rows = result.stdout.splitlines()
    for line in sorted(rows, key=lambda row: ("free" not in row.casefold(), row.casefold())):
        tier = "free-logged" if logged_free(line) else ("free" if "free" in line.casefold() else "paid")
        print(f"{line}\t-\t{tier}")

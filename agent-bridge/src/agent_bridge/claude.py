import json
import os
import select
import signal
import subprocess
import uuid
from pathlib import Path

from .core import (
    MESSAGING_RULE,
    POLL,
    REDELIVERED,
    capped,
    confirm_steer,
    log,
    poll_steers,
    route_to_peers,
    runner_finished,
    runner_started,
    save,
    worker_env,
)


def command(state, job, resume=False):
    cmd = [
        "claude",
        "-p",
        "--input-format",
        "stream-json",
        "--output-format",
        "stream-json",
        "--verbose",
        "--replay-user-messages",
        "--permission-prompts",
        "none",
        "--append-system-prompt",
        MESSAGING_RULE,
    ]
    if state.get("model"):
        cmd += ["--model", state["model"]]
    if state.get("effort"):
        cmd += ["--effort", state["effort"]]
    if resume and state.get("sessionId"):
        cmd += ["--resume", state["sessionId"]]
    write = state["sandbox"] == "workspace-write"
    roots = [p for p in state.get("writableRoots", []) if p != state["cwd"]] if write else []
    sandbox = {"enabled": True, "failIfUnavailable": True, "allowUnsandboxedCommands": False}
    sandbox["filesystem"] = {"allowWrite": roots}
    # workers never spawn agents; read-only also loses every file-writing tool
    denied = ["Agent"] if write else ["Agent", "Edit", "Write", "NotebookEdit"]
    cmd += ["--permission-mode", "auto" if write else "dontAsk", "--disallowedTools", *denied]
    for root in roots:
        cmd += ["--add-dir", root]
    # A settings allow rule WebFetch(domain:*) pre-allows every host for sandboxed commands (sandboxing docs),
    # matching codex workspace-write's full network.
    permissions = {"allow": ["WebFetch(domain:*)"]} if write else {}
    settings = {"sandbox": sandbox, "permissions": permissions, "env": {"CLAUDE_CODE_PLUGIN_DIRS": ""}}
    settings_path = Path(job) / "claude-settings.json"
    settings_path.write_text(json.dumps(settings), encoding="utf-8")
    cmd += ["--settings", str(settings_path)]
    return cmd


def process(event, state, job):
    typ = event.get("type")
    if typ == "system" and event.get("subtype") == "init":
        state["sessionId"] = event.get("session_id", state.get("sessionId", ""))
        save(Path(job) / "state.json", state)
        log(job, "thread_started", sessionId=state["sessionId"], model=event.get("model"))
        return False
    elif typ == "system" and event.get("subtype") == "compact_boundary":
        metadata = event["compact_metadata"]
        log(job, "compacted", pre_tokens=metadata["pre_tokens"], trigger=metadata["trigger"])
    elif typ == "assistant":
        activity = False
        for block in (event.get("message") or {}).get("content", []):
            if block.get("type") == "text":
                text = block.get("text", "").strip()
                if text:
                    urgent = text.lstrip().upper().startswith("URGENT:")
                    routed = text.lstrip()[7:].lstrip() if urgent else text
                    log(
                        job,
                        "message",
                        level="urgent" if urgent else "info",
                        text=routed,
                    )
                    route_to_peers(job, routed)
                    activity = True
            elif block.get("type") == "tool_use":
                name, inp = block.get("name", "tool"), block.get("input") or {}
                log(
                    job,
                    "command_start",
                    tool=name,
                    command=inp.get("command") if name == "Bash" else {"tool": name, "input": inp},
                )
                activity = True
        return False if activity or typ == "assistant" else None
    elif typ == "user":
        # a string is a replayed stdin message (--replay-user-messages); a list carries tool results
        content = (event.get("message") or {}).get("content", "")
        blocks = content if isinstance(content, list) else [{"type": "text", "text": content}]
        for block in blocks:
            if block.get("type") == "tool_result":
                log(job, "command_end", tool_use_id=block.get("tool_use_id"), is_error=block.get("is_error"))
        inflight = state.get("inflight")
        if inflight:
            text = "\n".join(block.get("text", "") for block in blocks if block.get("type") == "text")
            original = (Path(job) / "steer" / inflight["file"]).read_text(encoding="utf-8").strip()
            if text in (original, f"{REDELIVERED}\n{original}"):
                confirm_steer(job, state)
    elif typ == "result":
        idle = event.get("queued_turn_count", 0) == 0
        state["activeTurnId"] = None if idle else state.get("activeTurnId")
        save(Path(job) / "state.json", state)
        log(
            job,
            "turn_completed",
            subtype=event.get("subtype"),
            is_error=event.get("is_error"),
            usage=event.get("usage"),
            modelUsage=event.get("modelUsage"),
            total_cost_usd=event.get("total_cost_usd"),
            num_turns=event.get("num_turns"),
            stop_reason=event.get("stop_reason"),
            terminal_reason=event.get("terminal_reason"),
            queued_turn_count=event.get("queued_turn_count"),
            permission_denials=event.get("permission_denials"),
        )
        for denial in event.get("permission_denials", []):
            log(job, "permission_denied", level="urgent", denial=denial)
        return idle
    elif typ == "system" and event.get("subtype") in {"task_started", "task_notification", "task_updated"}:
        log(job, event["subtype"], **{k: v for k, v in event.items() if k not in ("type", "subtype")})
    elif typ == "rate_limit_event":
        log(job, "rate_limit_event", **{k: v for k, v in event.items() if k != "type"})
    elif typ == "control_response":
        log(
            job,
            "control_response",
            subtype=event.get("subtype"),
            request_id=event.get("request_id"),
            response=event.get("response"),
        )
    elif typ == "system" and event.get("subtype") == "permission_denied":
        log(
            job,
            "permission_denied",
            level="urgent",
            message=event.get("message"),
            tool_name=event.get("tool_name"),
        )


def run(job, state, path, prompt, resume=False, compact=False):
    if compact:
        if state.get("activeTurnId"):
            raise RuntimeError("job has an active turn; stop it before compacting")
        if not resume or not state.get("sessionId"):
            raise RuntimeError("claude compact requires an existing session")
        prompt = "/compact"
    if not prompt and not list((Path(job) / "steer").glob("[0-9]*.md")):
        return
    cmd = command(state, job, resume)
    proc = subprocess.Popen(
        capped(cmd),
        cwd=state["cwd"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=(Path(job) / "claude.stderr.log").open("a", encoding="utf-8"),
        env=worker_env(job),
        bufsize=0,
        start_new_session=True,
    )
    runner_started(state, path)
    buf = b""
    idle = False
    message_id = 0
    compacted = False

    def send(text):
        nonlocal idle, message_id
        proc.stdin.write(
            (json.dumps({"type": "user", "message": {"role": "user", "content": text}}) + "\n").encode()
        )
        proc.stdin.flush()
        message_id += 1
        idle = False
        state["activeTurnId"] = f"turn-{message_id}"
        save(path, state)

    stdin_closed = False
    try:
        if not compact and state.get("inflight"):
            poll_steers(job, send, state=state, defer=True, redeliver=True)
        if prompt:
            send(prompt)
            if compact:
                log(job, "compact_started")
        while True:
            ready, _, _ = select.select([proc.stdout], [], [], POLL)
            if ready:
                data = os.read(proc.stdout.fileno(), 1 << 20)
                if not data:
                    if not compact and list((Path(job) / "steer").glob("[0-9]*.md")):
                        log(job, "steer_queued", level="urgent", message="resume to deliver")
                        return
                    if not idle:
                        message = f"claude exited mid-turn (code {proc.poll()}); see claude.stderr.log"
                        raise RuntimeError(message)
                    return
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    try:
                        event = json.loads(line)
                        status = process(event, state, job)
                        if compact:
                            if event.get("type") == "system" and event.get("subtype") == "compact_boundary":
                                compacted = True
                                print(f"compacted: pre_tokens={event['compact_metadata']['pre_tokens']}")
                            elif event.get("type") == "result":
                                if event.get("subtype") != "success" or event.get("is_error"):
                                    reason = (event.get("result") or event.get("errors")
                                              or event.get("subtype"))
                                    raise RuntimeError(f"claude compact failed: {reason}")
                                if not compacted:
                                    reason = event.get("result") or "no compact_boundary event received"
                                    log(job, "compact_noop", text=reason)
                                    print(f"compact: no-op: {reason}")
                        if status is not None:
                            idle = status
                    except json.JSONDecodeError:
                        pass
            if (Path(job) / "interrupt").exists():
                (Path(job) / "interrupt").unlink()
                request_id = f"interrupt-{uuid.uuid4().hex}"
                proc.stdin.write(
                    (
                        json.dumps(
                            {
                                "type": "control_request",
                                "request_id": request_id,
                                "request": {"subtype": "interrupt"},
                            }
                        )
                        + "\n"
                    ).encode()
                )
                proc.stdin.flush()
                log(job, "interrupt_sent", request_id=request_id)
            if (Path(job) / "stop").exists():
                (Path(job) / "stop").unlink()
                log(job, "stopped")
                os.killpg(proc.pid, signal.SIGTERM)
                return
            if not compact and not stdin_closed:
                poll_steers(job, send, state=state, defer=True)
            elif not compact and list((Path(job) / "steer").glob("[0-9]*.md")):
                log(job, "steer_queued", level="urgent", message="resume to deliver")
                return
            if idle and (compact or not list((Path(job) / "steer").glob("[0-9]*.md"))):
                if not stdin_closed:
                    proc.stdin.close()
                    stdin_closed = True
    except Exception as exc:
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
                    log(job, "error", message="claude process group did not exit after SIGKILL")
        state["activeTurnId"] = None
        runner_finished(state, path)


def models():
    for model in ("sonnet", "opus", "haiku"):
        print(f"{model}\t-\talias")

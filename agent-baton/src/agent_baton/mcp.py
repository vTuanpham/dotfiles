"""Typed MCP boundary; existing CLI controllers own handoffs and secret handling."""

import asyncio
import os
import sys
from typing import Annotated

from mcp.server import MCPServer
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr

from agent_baton import core

server = MCPServer(
    "agent-baton",
    instructions=(
        "Pass your conversation's session on every call: codex:<CODEX_THREAD_ID>, "
        "claude:<CLAUDE_CODE_SESSION_ID>, or explicit:<unique conversation id>. "
        "Never use another conversation's id. Use native questions first; only the root sends reminders. "
        "Ask collects secrets from the human; tools never accept or return secret values. "
        "env_secret has a human enter a secret into environment files; never provide secret values. "
        "Focus the approved window, click its field with your browser tool, then type_answer. "
        "Verify submission before forget. wait is nonblocking by default; use the CLI's "
        "wait --until-done in a background command for event waits. "
        "Cancellation, expiry and silence are never approval."
    ),
)
Text = Annotated[StrictStr, Field(min_length=1)]
Reason = Annotated[StrictStr, Field(max_length=300)]
TTL = Annotated[int, Field(strict=True, ge=1)]


class Result(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    exit_code: int
    output: str


class SecretField(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: Annotated[StrictStr, Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")]
    label: Annotated[StrictStr, Field(min_length=1, max_length=60)]
    secret: StrictBool = True


def environment(session):
    """A per-call environment keeps concurrent MCP sessions out of each other's state."""
    namespace, separator, identifier = session.partition(":")
    keys = {namespace: key for key, namespace in core.SESSION_KEYS}
    if separator != ":" or namespace not in keys:
        raise ValueError("session must be codex:<id>, claude:<id> or explicit:<id>")
    identity = {keys[namespace]: identifier}
    core.session(identity)
    return {**{k: v for k, v in os.environ.items() if k not in dict(core.SESSION_KEYS)}, **identity}


async def invoke(session, *args, timeout=60):
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "agent_baton.cli", *args,
        env=environment(session), stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout)
    except BaseException:
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise
    return Result(exit_code=process.returncode, output=(stdout + stderr).decode("utf-8"))


@server.tool()
async def question(
    session: Text, question: Text, options: list[Text] | None = None,
    multiple: StrictBool = False, reason: Reason = "", ttl: TTL | None = None,
) -> Result:
    """Ask an ordinary question; never put credentials in it. Only the root sends reminders."""
    args = ["question", f"--reason={reason}"]
    for option in options or []:
        args.append(f"--option={option}")
    if multiple:
        args.append("--multiple")
    if ttl is not None:
        args.append(f"--ttl={ttl}")
    return await invoke(session, *args, "--", question)


@server.tool()
async def ask(
    session: Text, windows: Annotated[list[Text], Field(min_length=1)],
    fields: Annotated[list[SecretField], Field(min_length=1)],
    reason: Reason = "", ttl: TTL | None = None,
) -> Result:
    """Have the human enter secrets privately for the listed approved window titles. No values accepted."""
    args = ["ask", f"--reason={reason}", *(f"--window={window}" for window in windows)]
    if ttl is not None:
        args.append(f"--ttl={ttl}")
    args.extend(["--", *(f"{f.name}{':secret' if f.secret else ''}={f.label}" for f in fields)])
    return await invoke(session, *args)


@server.tool()
async def env_secret(
    session: Text, name: Text, files: Annotated[list[Text], Field(min_length=1)],
    prefix: StrictStr = "", reason: Reason = "", ttl: TTL | None = None,
) -> Result:
    """Have the human enter a secret privately and store it in the listed environment files."""
    args = ["env", name, f"--reason={reason}", *(f"--file={path}" for path in files)]
    if prefix:
        args.append(f"--prefix={prefix}")
    if ttl is not None:
        args.append(f"--ttl={ttl}")
    return await invoke(session, *args)


@server.tool()
async def status(session: Text) -> Result:
    """List only this conversation's handoffs, without secret values."""
    return await invoke(session, "status")


@server.tool()
async def wait(
    session: Text, id: Text, timeout_seconds: Annotated[int, Field(strict=True, ge=0, le=30)] = 0,
) -> Result:
    """Read an ordinary answer or secret readiness; exit 75 means pending. Never returns secrets."""
    return await invoke(session, "wait", id, f"--timeout={timeout_seconds}", timeout=timeout_seconds + 15)


@server.tool()
async def focus(session: Text, id: Text) -> Result:
    """Activate the human-approved window before selecting the input field. Types nothing."""
    return await invoke(session, "focus", f"--id={id}")


@server.tool()
async def type_answer(
    session: Text, id: Text, field: Text, clear: StrictBool = False, enter: StrictBool = False,
) -> Result:
    """Type a held answer by field name, after focus and field selection. Never supply its value."""
    args = ["type", f"--id={id}"]
    if clear:
        args.append("--clear")
    if enter:
        args.append("--enter")
    return await invoke(session, *args, "--", field)


@server.tool()
async def forget(session: Text, id: Text) -> Result:
    """Erase held answers after verifying that submission succeeded."""
    return await invoke(session, "forget", "--", id)


@server.tool()
async def withdraw(session: Text, id: Text) -> Result:
    """Withdraw this conversation's obsolete ordinary question; never grants approval."""
    return await invoke(session, "withdraw", "--", id)

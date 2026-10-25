"""Local ACP peer for SDK/runtime lifecycle tests; never calls a model."""

import asyncio
import os
import signal
import sys
import time
from pathlib import Path

from acp import run_agent
from acp.schema import (
    AgentCapabilities,
    InitializeResponse,
    ListSessionsResponse,
    LoadSessionResponse,
    PromptResponse,
    ResumeSessionResponse,
    SessionInfo,
    TextContentBlock,
    UserMessageChunk,
)


class FakeAgent:
    def __init__(self):
        self.connection = None
        self.cancelled = asyncio.Event()
        self.instance = f"{os.getpid()}-{time.monotonic_ns()}"
        self.hang_initialize = "--hang-init" in sys.argv

    def on_connect(self, connection):
        self.connection = connection

    async def initialize(self, protocol_version, **kwargs):
        if self.hang_initialize:
            await asyncio.Event().wait()
        if protocol_version != 1:
            raise ValueError("Only ACP v1 is supported by this fixture")
        return InitializeResponse(
            protocol_version=1,
            agent_capabilities=AgentCapabilities(
                load_session=True,
                prompt_capabilities={"image": True},
                session_capabilities={"list": {}, "resume": {}},
            ),
            auth_methods=[],
        )

    async def list_sessions(self, cwd=None, cursor=None, **kwargs):
        if cursor is not None:
            raise ValueError("Unexpected fixture cursor")
        sessions = [
            SessionInfo(session_id="fake-root", cwd="/project", title="Fake root " + self.instance),
            SessionInfo(session_id="other-root", cwd="/other", title="Other root"),
        ]
        if cwd is not None:
            sessions = [session for session in sessions if session.cwd == cwd]
        return ListSessionsResponse(sessions=sessions)

    async def load_session(self, cwd, session_id, mcp_servers, additional_directories=None, **kwargs):
        if "--hang-load" in sys.argv:
            Path(sys.argv[sys.argv.index("--hang-load") + 1]).touch()
            await asyncio.Event().wait()
        if session_id not in ("fake-root", "other-root"):
            raise ValueError("Unknown fake session")
        if mcp_servers != []:
            raise ValueError("Unexpected fake MCP servers")
        await self.connection.session_update(
            session_id,
            UserMessageChunk(
                session_update="user_message_chunk",
                message_id="loaded-user",
                content=TextContentBlock(type="text", text="Loaded history"),
            ),
        )
        return LoadSessionResponse()

    async def resume_session(self, session_id, cwd, additional_directories=None, mcp_servers=None, **kwargs):
        if session_id not in ("fake-root", "other-root"):
            raise ValueError("Unknown fake session")
        return ResumeSessionResponse()

    async def prompt(self, session_id, prompt, **kwargs):
        text = "".join(part.text for part in prompt if isinstance(part, TextContentBlock))
        if text == "crash":
            os._exit(23)
        await self.connection.session_update(
            session_id,
            UserMessageChunk(
                session_update="user_message_chunk",
                message_id="prompt-user",
                content=TextContentBlock(type="text", text=text),
            ),
        )
        if text == "request permission":
            response = await self.connection.request_permission(
                session_id=session_id,
                tool_call={"toolCallId": "permission-tool", "title": "Write a file"},
                options=[{"optionId": "allow", "name": "Allow", "kind": "allow_once"}],
            )
            if response.outcome.outcome != "cancelled":
                raise ValueError("Inbox unexpectedly granted permission")
            return PromptResponse(stop_reason="end_turn")
        await self.cancelled.wait()
        return PromptResponse(stop_reason="cancelled")

    async def cancel(self, session_id, **kwargs):
        if "--ignore-cancel" in sys.argv:
            return
        self.cancelled.set()


if "--spawn-descendants" in sys.argv:
    pid_file = Path(sys.argv[sys.argv.index("--spawn-descendants") + 1])
    child = os.fork()
    if child == 0:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        grandchild = os.fork()
        if grandchild == 0:
            while True:
                signal.pause()
        if "--fork-on-term" in sys.argv:
            def fork_on_term(signum, frame):
                if os.fork() == 0:
                    signal.signal(signal.SIGTERM, signal.SIG_IGN)
                    with pid_file.open("a") as stream:
                        stream.write(f" {os.getpid()}")
                    while True:
                        signal.pause()

            signal.signal(signal.SIGTERM, fork_on_term)
        pid_file.write_text(f"{os.getppid()} {os.getpid()} {grandchild}")
        while True:
            signal.pause()

asyncio.run(run_agent(FakeAgent()))

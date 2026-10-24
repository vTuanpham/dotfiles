"""Local ACP peer for SDK/runtime lifecycle tests; never calls a model."""

import asyncio
import os
import sys
import time

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
        await self.connection.session_update(
            session_id,
            UserMessageChunk(
                session_update="user_message_chunk",
                message_id="prompt-user",
                content=TextContentBlock(type="text", text=text),
            ),
        )
        await self.cancelled.wait()
        return PromptResponse(stop_reason="cancelled")

    async def cancel(self, session_id, **kwargs):
        self.cancelled.set()


asyncio.run(run_agent(FakeAgent()))

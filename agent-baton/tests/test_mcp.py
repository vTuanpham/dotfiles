import asyncio
import json
import os
import sys

import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters

from agent_baton import core, mcp


async def call(name, **arguments):
    async with Client(mcp.server) as client:
        return await client.call_tool(name, arguments)


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_BATON_HOME", str(tmp_path))
    monkeypatch.setenv("AGENT_BATON_CONFIG", str(tmp_path / "config.toml"))
    monkeypatch.setattr(core, "BATONS", tmp_path / "batons")
    for key, _ in core.SESSION_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("CODEX_THREAD_ID", "session-a")
    return monkeypatch


def test_native_tools_keep_conversations_isolated_and_never_return_secret_values(state):
    private = "private-canary-not-for-output"
    a = core.create("a.invalid", "", "Codex", 600, kind="ask", answered=True,
                    fields=[{"name": "password"}], password=private)
    state.setenv("CODEX_THREAD_ID", "session-b")
    b = core.create("b.invalid", "", "Codex", 600)

    async def check():
        results = await asyncio.gather(
            call("status", session="codex:session-a"),
            call("status", session="codex:session-b"),
        )
        left, right = [r.structured_content["output"] for r in results]
        assert a["id"] in left and b["id"] not in left
        assert b["id"] in right and a["id"] not in right
        ready = await call("wait", session="codex:session-a", id=a["id"])
        assert "received: password" in ready.structured_content["output"]
        assert private not in json.dumps(ready.model_dump())
        foreign = await call("forget", session="codex:session-b", id=a["id"])
        assert foreign.structured_content["exit_code"] != 0
        assert core.read(a["id"])["status"] == "held"
        pending = await call("wait", session="codex:session-b", id=b["id"])
        assert pending.structured_content["exit_code"] == 75
    asyncio.run(check())
    assert os.environ["CODEX_THREAD_ID"] == "session-b"


@pytest.mark.parametrize("session", ["", "shared", "codex:", "codex:two words", "other:a"])
def test_invalid_session_is_rejected_before_starting_a_process(session, state):
    result = asyncio.run(call("status", session=session))
    assert result.is_error
    assert not core.BATONS.exists()


def test_native_boundary_rejects_coercion_and_secret_payloads(state):
    async def check():
        for arguments in (
            {"session": "codex:session-a", "windows": ["Browser"],
             "fields": [{"name": "password", "label": "Password", "value": "must-not-be-accepted"}]},
            {"session": "codex:session-a", "windows": [], "fields": []},
            {"session": "codex:session-a", "windows": ["Browser"],
             "fields": [{"name": "password", "label": "Password", "secret": "true"}]},
        ):
            result = await call("ask", **arguments)
            assert result.is_error
        result = await call("wait", session="codex:session-a", id="test", timeout_seconds="2")
        assert result.is_error
    asyncio.run(check())
    assert not core.BATONS.exists()


def test_question_arguments_stay_data_and_preserve_multiple_selection(monkeypatch):
    captured = []

    async def invoke(session, *args, **kwargs):
        captured.append((session, args))
        return mcp.Result(exit_code=0, output="asked")

    monkeypatch.setattr(mcp, "invoke", invoke)
    result = asyncio.run(call("question", session="explicit:unique", question="--not-a-flag",
                              options=["--one", "$(unchanged)"], multiple=True))
    assert not result.is_error
    assert captured == [("explicit:unique", (
        "question", "--reason=", "--option=--one", "--option=$(unchanged)",
        "--multiple", "--", "--not-a-flag",
    ))]


def test_stdio_entrypoint_advertises_the_native_tools_and_keeps_protocol_output_clean(state):
    async def check():
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "agent_baton.cli", "mcp"], env=dict(os.environ),
        )
        async with Client(params) as client:
            tools = await client.list_tools()
            names = {tool.name for tool in tools.tools}
            assert names == {
                "ask", "question", "status", "wait", "focus", "type_answer", "forget", "withdraw",
            }
            result = await client.call_tool("status", {"session": "codex:session-a"})
            assert result.structured_content == {"exit_code": 0, "output": "no baton\n"}
    asyncio.run(check())

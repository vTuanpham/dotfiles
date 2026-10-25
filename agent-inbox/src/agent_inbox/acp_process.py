"""Own an ACP subprocess and its inherited POSIX process group."""

import asyncio
import os
import signal
from contextlib import asynccontextmanager, suppress

TERMINATE_GRACE = 0.2
KILL_TIMEOUT = 2


async def exited(process):
    # Process.wait() can wait for EOF after the leader exits if descendants hold its pipes.
    while process.returncode is None:
        await asyncio.sleep(0.02)
    return process.returncode


def _signal(process, sig):
    try:
        if os.name == "posix":
            if process.returncode is not None:
                try:
                    os.kill(process.pid, 0)
                except ProcessLookupError:
                    pass
                else:
                    raise RuntimeError("ACP process ID was reused; descendant cleanup is unconfirmed")
            os.killpg(process.pid, sig)
        elif process.returncode is None:
            if sig == signal.SIGTERM:
                process.terminate()
            else:
                process.kill()
    except ProcessLookupError:
        pass


@asynccontextmanager
async def agent_process(client, command, *, cwd, env, observers):
    from acp import connect_to_agent

    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        cwd=cwd,
        env=env,
        start_new_session=os.name == "posix",
    )
    connection = None
    try:
        connection = connect_to_agent(client, process.stdin, process.stdout, observers=observers)
        yield connection, process
    finally:
        # Reap descendants even after a clean leader exit; they may ignore TERM or fork on TERM.
        # shortcut: descendants that create another session escape; use cgroups if agents need that.
        try:
            process.stdin.close()
            _signal(process, signal.SIGTERM)
            await asyncio.sleep(TERMINATE_GRACE)
        finally:
            _signal(process, signal.SIGKILL)
            if connection is not None:
                with suppress(TimeoutError):
                    await asyncio.wait_for(connection.close(), timeout=KILL_TIMEOUT)
            async with asyncio.timeout(KILL_TIMEOUT):
                while await process.stdout.read(65536):
                    pass
                with suppress(BrokenPipeError, ConnectionResetError):
                    await process.stdin.wait_closed()
                await process.wait()

"""Failure and cleanup paths exercised against the real SDK and a local peer."""

import asyncio
import os
import signal
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from queue import Queue
from types import SimpleNamespace

import pytest
from test_acp import detached_runtime, target

from agent_inbox import acp_process, acp_runtime


def fake_target(*arguments):
    return replace(target("fake-root"), settings={
        "command": [sys.executable, str(Path(__file__).with_name("acp_fake_agent.py")), *arguments],
    })


def wait_until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    pytest.fail("ACP lifecycle condition did not become true")


def running(pid):
    try:
        # Orphans can remain zombies until the host's init reaps them.
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] != "Z"
    except (FileNotFoundError, ProcessLookupError):
        return False


@pytest.mark.skipif(sys.platform != "linux", reason="Uses /proc to distinguish zombies")
@pytest.mark.parametrize("scenario", ["stop", "crash", "fork-on-term"])
def test_stop_and_crash_reap_agent_descendants_holding_pipes(tmp_path, scenario):
    pid_file = tmp_path / "pids"
    pool = acp_runtime.RuntimePool()
    actor = None
    pids = []
    try:
        arguments = ["--spawn-descendants", str(pid_file)]
        if scenario == "fork-on-term":
            arguments.append("--fork-on-term")
        selected = fake_target(*arguments)
        pool.call(selected, "snapshot", None, None)
        actor = pool.runtimes[acp_runtime.runtime_key(selected)]
        wait_until(lambda: pid_file.exists() and len(pid_file.read_text().split()) == 3)
        pids = [int(pid) for pid in pid_file.read_text().split()]
        assert len(pids) == 3 and all(running(pid) for pid in pids)
        if scenario == "crash":
            with pytest.raises(acp_runtime.RuntimeClosedError, match="unknown"):
                actor.request("send", [{"type": "text", "text": "crash"}], timeout=2)
            wait_until(lambda: not actor.thread.is_alive())
        else:
            actor.stop(timeout=2)
        pids = [int(pid) for pid in pid_file.read_text().split()]
        if scenario == "fork-on-term":
            assert len(pids) == 4
        wait_until(lambda: all(not running(pid) for pid in pids))
    finally:
        for pid in pids:
            if running(pid):
                os.kill(pid, signal.SIGKILL)
        if actor is not None:
            actor.thread.join(timeout=5)
        pool.close()


@pytest.mark.parametrize("hang_notification", [False, True])
def test_cancel_deadline_covers_notification_and_receipt_without_cancelling_prompt(monkeypatch,
                                                                                 hang_notification):
    runtime = detached_runtime()
    monkeypatch.setattr(acp_runtime, "CANCEL_TIMEOUT", 0.02, raising=False)

    async def ignore_cancel(**kwargs):
        if hang_notification:
            await asyncio.Event().wait()

    runtime.connection.cancel = ignore_cancel

    async def exercise():
        send = asyncio.create_task(runtime._perform("send", [{"type": "text", "text": "hello"}]))
        await runtime.connection.started.wait()
        try:
            with pytest.raises(TimeoutError, match="cancellation.*unknown"):
                await asyncio.wait_for(runtime._perform("cancel"), timeout=0.5)
            assert runtime.busy and not runtime._prompt_task.done()
            assert (await runtime._perform("snapshot", None, None))["status"] == "active"
        finally:
            runtime.connection.cancelled.set()
            assert await send == "cancelled"

    asyncio.run(exercise())


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group cleanup")
def test_reused_leader_pid_prevents_signalling_an_unrelated_process_group(monkeypatch):
    signals = []
    monkeypatch.setattr(acp_process.os, "kill", lambda pid, sig: None)
    monkeypatch.setattr(acp_process.os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    with pytest.raises(RuntimeError, match="reused"):
        acp_process._signal(SimpleNamespace(pid=123, returncode=23), signal.SIGKILL)
    assert signals == []


def test_shutdown_reaps_agent_even_if_native_cancel_never_finishes(monkeypatch):
    monkeypatch.setattr(acp_runtime, "CANCEL_TIMEOUT", 0.02)
    pool = acp_runtime.RuntimePool()
    selected = fake_target("--ignore-cancel")
    pool.call(selected, "snapshot", None, None)
    actor = pool.runtimes[acp_runtime.runtime_key(selected)]
    with ThreadPoolExecutor(max_workers=1) as executor:
        send = executor.submit(pool.call, selected, "send", [{"type": "text", "text": "hello"}])
        try:
            wait_until(lambda: pool.call(selected, "snapshot", None, None)["status"] == "active")
            with pytest.raises(RuntimeError, match="cleanly stop"):
                pool.close()
            assert not actor.thread.is_alive()
            with pytest.raises(acp_runtime.RuntimeClosedError, match="unknown"):
                send.result(timeout=2)
        finally:
            pool.close()


def test_hung_session_load_fails_attach_and_removes_starting_runtime(tmp_path):
    pool = acp_runtime.RuntimePool()
    marker = tmp_path / "load-entered"
    try:
        with pytest.raises(TimeoutError, match="attach"):
            pool._get_or_start(fake_target("--hang-load", str(marker)), "root", startup_timeout=2)
        assert marker.exists()
        assert pool.runtimes == {} and pool.starting == {}
    finally:
        pool.close()


@pytest.mark.parametrize("abandon_first", [False, True])
def test_raw_receipts_belong_to_their_request_even_after_timeout_or_out_of_order_resume(abandon_first):
    observer = acp_runtime._Observer()

    def wire(direction, message):
        observer(SimpleNamespace(direction=SimpleNamespace(value=direction), message=message))

    async def exercise():
        waiting = {1: asyncio.Event(), 2: asyncio.Event()}
        started = {1: asyncio.Event(), 2: asyncio.Event()}

        async def request(identifier):
            wire("outgoing", {"id": identifier, "method": "session/list"})
            started[identifier].set()
            await waiting[identifier].wait()
            return observer.take("session/list")

        first = asyncio.create_task(request(1))
        await started[1].wait()
        if abandon_first:
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
        second = asyncio.create_task(request(2))
        await started[2].wait()
        wire("incoming", {"id": 1, "result": {"sessions": ["old"]}})
        wire("incoming", {"id": 2, "result": {"sessions": ["current"]}})
        waiting[2].set()
        assert await second == {"sessions": ["current"]}
        if not abandon_first:
            waiting[1].set()
            assert await first == {"sessions": ["old"]}
        await asyncio.sleep(0)
        assert observer.methods == {} and observer.results == {}

    asyncio.run(exercise())


def test_crashed_runtime_reloads_history_without_retrying_the_prompt():
    selected = fake_target()
    pool = acp_runtime.RuntimePool()
    try:
        original = pool.call(selected, "snapshot", None, None)
        actor = pool.runtimes[acp_runtime.runtime_key(selected)]
        with pytest.raises(acp_runtime.RuntimeClosedError):
            pool.call(selected, "send", [{"type": "text", "text": "crash"}])
        wait_until(lambda: not actor.thread.is_alive())
        recovered = pool.call(selected, "snapshot", None, None)
        assert recovered["messages"] == original["messages"]
        assert pool.runtimes[acp_runtime.runtime_key(selected)] is not actor
    finally:
        pool.close()


def test_two_roots_run_and_cancel_independently():
    pool = acp_runtime.RuntimePool()
    one, two = fake_target(), replace(fake_target(), session_id="other-root")
    try:
        for selected in (one, two):
            pool.call(selected, "snapshot", None, None)
        with ThreadPoolExecutor(max_workers=2) as executor:
            sends = [executor.submit(pool.call, selected, "send", [{"type": "text", "text": "hello"}])
                     for selected in (one, two)]
            try:
                for selected in (one, two):
                    wait_until(lambda: pool.call(selected, "snapshot", None, None)["status"] == "active")
                assert pool.call(one, "cancel") == "applied"
                assert sends[0].result(timeout=2) == "cancelled"
                assert not sends[1].done()
                assert pool.call(two, "snapshot", None, None)["status"] == "active"
                assert pool.call(two, "cancel") == "applied"
                assert sends[1].result(timeout=2) == "cancelled"
            finally:
                pool.close()
    finally:
        pool.close()


def test_sdk_permission_request_is_declined_without_blocking_the_turn():
    selected = fake_target()
    pool = acp_runtime.RuntimePool()
    try:
        assert pool.call(selected, "send", [{"type": "text", "text": "request permission"}]) == "end_turn"
        assert pool.call(selected, "context")["denied_permissions"] == 1
    finally:
        pool.close()


def test_session_listing_deadline_cancels_a_single_hung_page(monkeypatch):
    monkeypatch.setattr(acp_runtime, "LIST_TIMEOUT", 0.02)

    class HangingConnection:
        cancelled = False

        async def list_sessions(self, **kwargs):
            try:
                await asyncio.Event().wait()
            finally:
                self.cancelled = True

    connection = HangingConnection()

    async def exercise():
        async with asyncio.timeout(0.5):
            with pytest.raises(TimeoutError):
                await acp_runtime._list_sessions(connection, None)
        assert connection.cancelled

    asyncio.run(exercise())


def test_closing_runtime_rejects_new_work_before_failing_pending_requests():
    actor = acp_runtime._SessionRuntime(fake_target(), startup_timeout=5)
    original = actor._fail_pending
    rejected = []

    def fail_pending(error):
        original(error)
        try:
            actor.request("snapshot", None, None, timeout=0)
        except Exception as closed:
            rejected.append(closed)

    actor._fail_pending = fail_pending
    actor.stop()
    assert len(rejected) == 1 and isinstance(rejected[0], acp_runtime.RuntimeClosedError)
    assert actor._pending == set() and actor.queue.empty()


def test_actor_timeout_is_not_relabelled_as_the_callers_wait_timeout():
    actor = detached_runtime()
    actor.thread = SimpleNamespace(is_alive=lambda: True)
    actor.loop = object()
    actor.queue = Queue()
    actor._pending = set()
    failure = TimeoutError("native cancellation was not confirmed")

    def finish():
        actor.queue.get_nowait().result.set_exception(failure)

    actor._signal = finish
    with pytest.raises(TimeoutError) as caught:
        actor.request("cancel")
    assert caught.value is failure and actor._pending == set()


def test_shutdown_surfaces_process_cleanup_failure_after_the_stop_receipt(monkeypatch):
    original = acp_process.agent_process

    @asynccontextmanager
    async def failing_cleanup(*arguments, **kwargs):
        async with original(*arguments, **kwargs) as peer:
            yield peer
        raise OSError("descendant cleanup failed")

    monkeypatch.setattr(acp_process, "agent_process", failing_cleanup)
    actor = acp_runtime._SessionRuntime(fake_target(), startup_timeout=5)
    with pytest.raises(RuntimeError, match="shutdown failed") as caught:
        actor.stop()
    assert isinstance(caught.value.__cause__, OSError)
    assert not actor.thread.is_alive()

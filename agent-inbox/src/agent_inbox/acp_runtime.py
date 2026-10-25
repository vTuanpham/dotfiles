"""Bounded, per-root ACP runtime using the official Python client SDK."""

import asyncio
import concurrent.futures
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue
from threading import Lock, Thread

from . import acp_history, acp_process
from .models import DeliveryRejected, fields, text

IDLE_SECONDS = 300
MAX_RUNTIMES = 4
START_TIMEOUT = 60
CALL_TIMEOUT = 30 * 60
CANCEL_TIMEOUT = 15
LIST_TIMEOUT = 8
LIST_PAGES = 50
DISCOVERY_TIMEOUT = 30
STOP_TIMEOUT = 120
STOP_JOIN_TIMEOUT = 10
_QUEUE_TIMEOUT = object()


class RuntimeClosedError(RuntimeError):
    """This connection cannot accept work; a prior native operation may have completed."""


def settings(target):
    fields(target.settings, ("command",), ("cwd", "bridge_backend"))
    command = target.settings["command"]
    if (
        type(command) is not list
        or not command
        or any(type(value) is not str or not value for value in command)
    ):
        raise ValueError("Invalid ACP command")
    if not Path(command[0]).is_absolute():
        raise ValueError("ACP executable must be absolute")
    cwd = target.settings.get("cwd")
    if cwd is not None:
        if type(cwd) is not str or not Path(cwd).is_absolute():
            raise ValueError("ACP process directory must be absolute")
    if "bridge_backend" in target.settings:
        text(target.settings["bridge_backend"], "Bridge backend", 100)
    return command, cwd


def _environment():
    from acp.transports import default_environment

    env = default_environment()
    for key in ("XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS"):
        if value := os.environ.get(key):
            env[key] = value
    return env


class _Observer:
    def __init__(self, history=None):
        self.history = history
        self.methods = {}
        self.results = {}
        self.error = None

    def __call__(self, event):
        message = event.message
        try:
            if event.direction.value == "outgoing":
                if "id" in message and type(message.get("method")) is str:
                    identifier, method = message["id"], message["method"]
                    task = asyncio.current_task()
                    self.methods[identifier] = (method, task)

                    def forget(task):
                        self.methods.pop(identifier, None)
                        self.results.pop((task, method), None)

                    task.add_done_callback(forget)
            elif message.get("method") == "session/update":
                if self.history is not None:
                    self.history.update(message.get("params"))
            elif "id" in message and message["id"] in self.methods:
                method, task = self.methods.pop(message["id"])
                if "result" in message and not task.done():
                    self.results[(task, method)] = message["result"]
        except Exception as error:
            if self.error is None:
                self.error = error

    def take(self, method):
        self.raise_if_error()
        key = (asyncio.current_task(), method)
        if key not in self.results:
            raise ValueError("ACP response was not captured")
        result = self.results.pop(key)
        if type(result) is not dict:
            raise ValueError("Invalid ACP response")
        return result

    def raise_if_error(self):
        if self.error is not None:
            raise self.error


class _Client:
    def __init__(self, session_id, history=None):
        self.session_id = session_id
        self.history = history

    async def session_update(self, session_id, update, **kwargs):
        # The stream observer decodes the original wire event synchronously.
        return None

    async def request_permission(self, session_id, tool_call, options, **kwargs):
        from acp.schema import RequestPermissionResponse

        if self.session_id is not None and session_id != self.session_id:
            raise ValueError("ACP permission request belongs to another session")
        if self.history is not None:
            self.history.denied_permissions += 1
        return RequestPermissionResponse(outcome={"outcome": "cancelled"})

    async def create_elicitation(self, message, mode, **kwargs):
        return {"action": "decline"}


def runtime_key(target, role="root"):
    command, cwd = settings(target)
    return json.dumps(
        [
            role,
            command,
            cwd,
            target.adapter,
            target.harness,
            target.session_id if role == "root" else None,
            target.settings.get("bridge_backend"),
        ],
        separators=(",", ":"),
    )


@dataclass
class _Request:
    operation: str
    arguments: tuple
    result: concurrent.futures.Future


class _SessionRuntime:
    def __init__(self, target, role="root", startup_timeout=START_TIMEOUT):
        self.target = target
        self.role = role
        self.startup_timeout = startup_timeout
        self.key = runtime_key(target, role)
        self.ready = concurrent.futures.Future()
        self.thread = Thread(target=self._thread_main, name="agent-inbox-acp", daemon=True)
        self.loop = None
        self.queue = Queue()
        self._wake_event = None
        self.connection = None
        self.observer = None
        self.capabilities = None
        self.history = acp_history.History(target.session_id) if role == "root" else None
        self.session = None
        self._state_lock = Lock()
        self._busy = False
        self._closing = False
        self._last_used = time.monotonic()
        self._pending = set()
        self._failure = None
        self._prompt_task = None
        self._dispatch_tasks = set()
        self.thread.start()
        try:
            self.ready.result(timeout=startup_timeout + 5)
        except concurrent.futures.TimeoutError as error:
            with self._state_lock:
                self._closing = True
            # Python's TimeoutError is concurrent.futures.TimeoutError, so this also catches the
            # actor's own attach timeout; only a still-starting actor needs the shutdown request.
            if self.loop is not None and not self.ready.done():
                result = concurrent.futures.Future()
                self.queue.put(_Request("shutdown", (), result))
                self._signal()
            self.thread.join(timeout=5)
            raise TimeoutError("ACP session attach timed out") from error

    @property
    def busy(self):
        with self._state_lock:
            return self._busy

    @property
    def last_used(self):
        with self._state_lock:
            return self._last_used

    @property
    def available(self):
        with self._state_lock:
            return not self._closing and self.thread.is_alive()

    def touch(self, busy=None):
        with self._state_lock:
            self._last_used = time.monotonic()
            if busy is not None:
                self._busy = busy

    def request(self, operation, *arguments, timeout=None):
        with self._state_lock:
            closing = self._closing
        if closing or not self.thread.is_alive() or self.loop is None:
            raise RuntimeClosedError("ACP runtime is not available")
        result = concurrent.futures.Future()
        request = _Request(operation, arguments, result)
        try:
            with self._state_lock:
                if self._closing:
                    raise RuntimeClosedError("ACP runtime is closing")
                self._pending.add(result)
                self.queue.put(request)
            self._signal()
            self.touch()
            return result.result(timeout=CALL_TIMEOUT if timeout is None else timeout)
        except concurrent.futures.TimeoutError as error:
            if result.done() and result.exception() is error:
                raise
            raise TimeoutError("ACP operation timed out; the native outcome is unknown") from error
        finally:
            with self._state_lock:
                if result.done():
                    self._pending.discard(result)

    def stop_if_idle(self, timeout=3):
        with self._state_lock:
            if self._busy:
                return False
        try:
            return self.stop(timeout)
        except RuntimeError:
            return False

    def stop(self, timeout=STOP_TIMEOUT):
        with self._state_lock:
            if not self.thread.is_alive():
                return True
            if self._closing or self.loop is None:
                closing = True
            else:
                self._closing = True
                closing = False
        if closing:
            self.thread.join(timeout=5)
            if self.thread.is_alive():
                raise RuntimeError("ACP runtime is still closing")
            return True
        result = concurrent.futures.Future()
        failure = None
        try:
            self.queue.put(_Request("shutdown", (), result))
            self._signal()
            result.result(timeout=timeout)
        except Exception as error:
            failure = error
        self.thread.join(timeout=STOP_JOIN_TIMEOUT)
        if self.thread.is_alive():
            raise RuntimeError("ACP runtime did not stop") from failure
        if failure is None and self._failure is not None:
            raise RuntimeError("ACP runtime shutdown failed") from self._failure
        if failure is not None:
            raise RuntimeError("ACP runtime stopped without a confirmed turn result") from failure
        return True

    def _signal(self):
        # Wake the actor from any thread. The queue is re-checked after each clear, so a wake
        # that lands before the event exists, or after the loop closed, loses no request.
        loop, event = self.loop, self._wake_event
        if loop is None or event is None:
            return
        try:
            loop.call_soon_threadsafe(event.set)
        except RuntimeError:
            pass  # loop closed: _serve's finally already failed every pending request

    def _thread_main(self):
        try:
            asyncio.run(self._serve())
        except Exception as error:
            if not self.ready.done():
                self.ready.set_exception(error)
            self._fail_pending(error)

    async def _serve(self):
        from acp.schema import ClientCapabilities, Implementation

        self.loop = asyncio.get_running_loop()
        self._wake_event = asyncio.Event()
        command, cwd = settings(self.target)
        observer = _Observer(self.history)
        client_session = self.target.session_id if self.role == "root" else None
        client = _Client(client_session, self.history)
        parameters = ClientCapabilities(
            fs={"readTextFile": False, "writeTextFile": False},
            terminal=False,
            session={"configOptions": {"boolean": {}}},
            auth={"terminal": False},
        )
        implementation = Implementation(name="agent-inbox", version="0.1.0")
        try:
            async with acp_process.agent_process(
                client,
                command,
                env=_environment(),
                cwd=cwd,
                observers=[observer],
            ) as (connection, process):
                self.connection, self.observer = connection, observer
                try:
                    await asyncio.wait_for(
                        self._attach(connection, observer, parameters, implementation),
                        timeout=self.startup_timeout,
                    )
                    self.ready.set_result(True)
                    await self._serve_requests(process)
                finally:
                    with self._state_lock:
                        self._closing = True
                    tasks = set(self._dispatch_tasks)
                    if self._prompt_task is not None:
                        tasks.add(self._prompt_task)
                    for task in tasks:
                        task.cancel()
                    if tasks:
                        await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as error:
            self._failure = error
            if not self.ready.done():
                self.ready.set_exception(error)
            self._fail_queued(error)
        finally:
            with self._state_lock:
                self._closing = True
            if not self.ready.done():
                self.ready.set_exception(RuntimeClosedError("ACP runtime stopped during startup"))
            self._fail_pending(
                self._failure or RuntimeClosedError("ACP connection closed; native outcome may be unknown")
            )
            self.connection = None

    async def _attach(self, connection, observer, parameters, implementation):
        response = await connection.initialize(
            protocol_version=1,
            client_capabilities=parameters,
            client_info=implementation,
        )
        self.capabilities = acp_history.initialize(observer.take("initialize"))
        if response.protocol_version != 1 or not self.capabilities.list:
            raise ValueError("ACP agent does not advertise session listing")
        if self.role == "source":
            return
        if not (self.capabilities.load and self.capabilities.resume):
            raise ValueError("ACP agent lacks required session lifecycle capabilities")
        sessions = await _list_sessions(connection, observer)
        matching = [item for item in sessions if item.id == self.target.session_id]
        if len(matching) != 1:
            raise DeliveryRejected("The selected ACP root is no longer available")
        self.session = matching[0]
        directories = (
            self.session.additional_directories if self.capabilities.additional_directories else None
        )
        await connection.load_session(
            cwd=self.session.cwd,
            session_id=self.session.id,
            mcp_servers=[],
            additional_directories=directories,
        )
        self.history.load(observer.take("session/load"))
        observer.raise_if_error()

    async def _serve_requests(self, process):
        process_exit = asyncio.create_task(acp_process.exited(process))
        while True:
            if self._prompt_task is not None and self._prompt_task.done():
                self._prompt_task = None
                self.touch(busy=False)
            try:
                request = await self._wait_request(process_exit, IDLE_SECONDS)
            except Exception:
                raise
            if request is _QUEUE_TIMEOUT:
                if self._prompt_task is None and not self._dispatch_tasks:
                    with self._state_lock:
                        self._closing = True
                    return
                continue
            if request.operation == "shutdown":
                shutdown_error = None
                try:
                    value = await self._perform("shutdown")
                except Exception as error:
                    shutdown_error = error
                    self._set_exception(request.result, error)
                else:
                    self._set_result(request.result, value)
                with self._state_lock:
                    self._closing = True
                if shutdown_error is not None:
                    tasks = tuple(self._dispatch_tasks)
                    for task in tasks:
                        task.cancel()
                    if tasks:
                        await asyncio.gather(*tasks, return_exceptions=True)
                await self._wait_dispatch_tasks()
                return
            if request.operation in ("snapshot", "controls", "permission_status"):
                await self._dispatch(request)
                continue
            task = asyncio.create_task(self._dispatch(request))
            self._dispatch_tasks.add(task)
            task.add_done_callback(self._dispatch_finished)

    async def _wait_request(self, process_exit, timeout):
        deadline = time.monotonic() + timeout
        while True:
            if process_exit.done():
                returncode = process_exit.result()
                raise RuntimeClosedError(
                    f"ACP agent process exited with status {returncode}; native outcome may be unknown"
                )
            try:
                return self.queue.get_nowait()
            except Empty:
                pass
            self._wake_event.clear()
            try:
                return self.queue.get_nowait()
            except Empty:
                pass
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return _QUEUE_TIMEOUT
            woke = asyncio.create_task(self._wake_event.wait())
            done, _ = await asyncio.wait(
                (woke, process_exit), timeout=remaining, return_when=asyncio.FIRST_COMPLETED,
            )
            if process_exit in done:
                woke.cancel()
                returncode = process_exit.result()
                raise RuntimeClosedError(
                    f"ACP agent process exited with status {returncode}; native outcome may be unknown"
                )
            if woke not in done:
                woke.cancel()
                return _QUEUE_TIMEOUT

    def _dispatch_finished(self, task):
        self._dispatch_tasks.discard(task)
        try:
            task.result()
        except BaseException:
            # _dispatch resolves the request future with the error; consume the task exception here.
            pass

    async def _wait_dispatch_tasks(self):
        pending = tuple(self._dispatch_tasks)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def _dispatch(self, request):
        try:
            result = await asyncio.wait_for(
                self._perform(request.operation, *request.arguments), timeout=CALL_TIMEOUT,
            )
        except asyncio.CancelledError:
            self._set_exception(
                request.result,
                RuntimeClosedError("ACP operation was interrupted; native outcome is unknown"),
            )
            raise
        except ConnectionError as error:
            self._set_exception(
                request.result,
                RuntimeClosedError(f"ACP connection closed; native outcome is unknown: {error}"),
            )
        except Exception as error:
            self._set_exception(request.result, error)
        else:
            self._set_result(request.result, result)

    def _set_result(self, future, value):
        with self._state_lock:
            self._pending.discard(future)
            if not future.done():
                future.set_result(value)

    def _set_exception(self, future, error):
        with self._state_lock:
            self._pending.discard(future)
            if not future.done():
                future.set_exception(error)

    def _fail_pending(self, error):
        with self._state_lock:
            for future in tuple(self._pending):
                if not future.done():
                    future.set_exception(error)
            self._pending.clear()

    async def _perform(self, operation, *arguments):
        if operation == "discover":
            if self.role != "source":
                raise ValueError("ACP discovery requires the source runtime")
            timeout = arguments[0] if arguments else DISCOVERY_TIMEOUT
            return await asyncio.wait_for(
                _list_sessions(self.connection, self.observer), timeout=timeout,
            )
        if operation in ("send", "slash", "cancel", "mode", "config") and self.session is None:
            raise ValueError("ACP source runtime cannot control a root session")
        if operation == "snapshot":
            if self.history is None:
                raise ValueError("ACP source runtime has no root history")
            cursor, since = arguments
            messages, activity, timeline, older, newer, catching_up = self.history.page(cursor, since)
            status = "active" if self._prompt_task is not None and not self._prompt_task.done() else "unknown"
            self.touch()
            return {
                "status": status,
                "can_send": status != "active",
                "messages": messages,
                "older_cursor": older,
                "newer_cursor": newer,
                "catching_up": catching_up,
                "activity": activity,
                "timeline": timeline,
            }
        if operation == "controls":
            if self.history is None:
                raise ValueError("ACP source runtime has no root controls")
            self.touch()
            return {
                "commands": list(self.history.commands),
                "modes": self.history.modes,
                "config_options": list(self.history.config_options),
                "active": self._prompt_task is not None and not self._prompt_task.done(),
            }
        if operation == "context":
            if self.history is None:
                return {"usage": None, "denied_permissions": 0}
            return {"usage": self.history.usage, "denied_permissions": self.history.denied_permissions}
        if operation == "send":
            content = arguments[0]
            if self._prompt_task is not None and not self._prompt_task.done():
                raise DeliveryRejected("This ACP root is already processing a turn")
            if any(block.get("type") == "image" for block in content) and not self.capabilities.image:
                raise DeliveryRejected("This ACP agent does not accept image prompts")
            self.observer.raise_if_error()
            self._prompt_task = asyncio.create_task(self._prompt(content))
            self.touch(busy=True)
            return await asyncio.shield(self._prompt_task)
        if operation == "slash":
            name, value = arguments
            if name not in {command.name for command in self.history.commands}:
                raise DeliveryRejected("ACP slash command is no longer available")
            prompt = "/" + name + (" " + value if value else "")
            return await self._perform("send", [{"type": "text", "text": prompt}])
        if operation == "cancel":
            if self._prompt_task is None or self._prompt_task.done():
                raise DeliveryRejected("This ACP root has no active inbox turn")
            task = self._prompt_task
            try:
                async with asyncio.timeout(CANCEL_TIMEOUT):
                    await self.connection.cancel(session_id=self.session.id)
                    response = await asyncio.shield(task)
            except asyncio.TimeoutError as error:
                raise TimeoutError("ACP cancellation timed out; the native outcome is unknown") from error
            if response != "cancelled":
                raise DeliveryRejected("The ACP turn completed before cancellation")
            self.touch(busy=False)
            return "applied"
        if operation == "mode":
            mode_id = arguments[0]
            if self.history.modes is None or mode_id not in {key for key, _ in self.history.modes.choices}:
                raise DeliveryRejected("ACP mode is no longer available")
            await self.connection.set_session_mode(session_id=self.session.id, mode_id=mode_id)
            self.observer.take("session/set_mode")
            self.observer.raise_if_error()
            self.history.modes = acp_history.Mode(mode_id, self.history.modes.choices)
            self.touch()
            return "applied"
        if operation == "config":
            config_id, value = arguments
            options = [option for option in self.history.config_options if option.id == config_id]
            if len(options) != 1:
                raise DeliveryRejected("ACP configuration option is no longer available")
            option = options[0]
            if option.kind == "boolean":
                if type(value) is not bool:
                    raise DeliveryRejected("ACP boolean option has an invalid value")
            elif type(value) is not str or value not in {choice for choice, _ in option.choices}:
                raise DeliveryRejected("ACP configuration choice is no longer available")
            await self.connection.set_config_option(
                config_id=config_id, session_id=self.session.id, value=value
            )
            result = self.observer.take("session/set_config_option")
            self.observer.raise_if_error()
            if "configOptions" not in result:
                raise ValueError("ACP configuration receipt omitted complete state")
            _, config_options = acp_history.load_state(result)
            if config_options is None:
                raise ValueError("ACP configuration receipt omitted complete state")
            self.history.config_options = config_options
            self.touch()
            return "applied"
        if operation == "shutdown":
            if self._prompt_task is not None and not self._prompt_task.done():
                task = self._prompt_task
                try:
                    async with asyncio.timeout(CANCEL_TIMEOUT):
                        await self.connection.cancel(session_id=self.session.id)
                        await asyncio.shield(task)
                except asyncio.TimeoutError as error:
                    raise RuntimeError("ACP turn did not stop before runtime shutdown") from error
            self.touch()
            return "stopped"
        raise ValueError("Unknown ACP runtime operation")

    async def _prompt(self, content):
        try:
            response = await self.connection.prompt(session_id=self.session.id, prompt=content)
            result = self.observer.take("session/prompt")
            self.observer.raise_if_error()
            fields(result, ("stopReason",), ("usage", "_meta"))
            if response.stop_reason != result["stopReason"] or result["stopReason"] not in (
                "end_turn",
                "max_tokens",
                "max_turn_requests",
                "refusal",
                "cancelled",
            ):
                raise ValueError("Invalid ACP prompt receipt")
            return result["stopReason"]
        finally:
            self.history.end_turn()
            self.touch(busy=False)

    def _fail_queued(self, error):
        if self.queue is None:
            return
        while True:
            try:
                request = self.queue.get_nowait()
            except Empty:
                break
            self._set_exception(request.result, error)


class RuntimePool:
    """Small per-root process pool; live prompts share the same reader and connection."""

    def __init__(self, runtime_factory=None, discovery_timeout=DISCOVERY_TIMEOUT):
        self.lock = Lock()
        self.runtimes = {}
        self.starting = {}
        self.closed = False
        self.runtime_factory = runtime_factory or _SessionRuntime
        self.discovery_timeout = discovery_timeout

    def discover(self, target):
        deadline = time.monotonic() + self.discovery_timeout
        runtime = self._get_or_start(target, "source", startup_timeout=self.discovery_timeout)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("ACP source discovery timed out")
        return runtime.request("discover", remaining, timeout=remaining + 2)

    def call(self, target, operation, *arguments):
        runtime = self._get_or_start(target, "root", startup_timeout=START_TIMEOUT)
        return runtime.request(operation, *arguments)

    def _get_or_start(self, target, role, startup_timeout):
        key = runtime_key(target, role)
        creator = False
        with self.lock:
            if self.closed:
                raise RuntimeError("ACP runtime pool is closed")
            runtime = self.runtimes.get(key)
            if runtime is not None and not runtime.available:
                runtime.thread.join(timeout=3)
                if runtime.thread.is_alive():
                    raise RuntimeError("ACP runtime is still closing")
                self.runtimes.pop(key, None)
                runtime = None
            if runtime is not None:
                startup = None
            elif key in self.starting:
                startup = self.starting[key]
            else:
                self._make_room()
                startup = concurrent.futures.Future()
                self.starting[key] = startup
                creator = True
        if runtime is None:
            if creator:
                try:
                    runtime = self.runtime_factory(target, role, startup_timeout)
                except Exception as error:
                    with self.lock:
                        if self.starting.get(key) is startup:
                            self.starting.pop(key, None)
                    if not startup.done():
                        startup.set_exception(error)
                    raise
                closed = False
                with self.lock:
                    self.starting.pop(key, None)
                    if self.closed:
                        closed = True
                    else:
                        self.runtimes[key] = runtime
                if closed:
                    try:
                        runtime.stop()
                    finally:
                        if not startup.done():
                            startup.set_exception(RuntimeError("ACP runtime pool closed during startup"))
                    raise RuntimeError("ACP runtime pool closed during startup")
                if not startup.done():
                    startup.set_result(runtime)
            else:
                runtime = startup.result(timeout=startup_timeout + 5)
        return runtime

    def _make_room(self):
        stale = [
            key
            for key, runtime in self.runtimes.items()
            if not runtime.busy and time.monotonic() - runtime.last_used >= IDLE_SECONDS
        ]
        for key in stale:
            runtime = self.runtimes[key]
            if runtime.stop_if_idle():
                self.runtimes.pop(key, None)
            elif not runtime.thread.is_alive():
                self.runtimes.pop(key, None)
            elif runtime.busy:
                continue
            else:
                raise RuntimeError("Could not stop a stale ACP runtime")
        if len(self.runtimes) + len(self.starting) < MAX_RUNTIMES:
            return
        idle = [
            (runtime.last_used, key, runtime) for key, runtime in self.runtimes.items() if not runtime.busy
        ]
        if not idle:
            raise RuntimeError("ACP runtime capacity is full; an active turn is still running")
        _, key, runtime = min(idle)
        if not runtime.stop_if_idle():
            raise RuntimeError("Could not close the idle ACP runtime")
        self.runtimes.pop(key, None)

    def close(self):
        with self.lock:
            self.closed = True
            starting = list(self.starting.values())
        for future in starting:
            try:
                future.result(timeout=START_TIMEOUT + 10)
            except Exception:
                pass
        with self.lock:
            runtimes = list(self.runtimes.values())
        failures = []
        for runtime in runtimes:
            try:
                runtime.stop()
            except Exception as error:
                failures.append(error)
        if failures:
            with self.lock:
                self.closed = False
            raise RuntimeError(f"Could not cleanly stop {len(failures)} ACP runtime(s)") from failures[0]
        with self.lock:
            self.runtimes.clear()
            if self.starting:
                self.closed = False
                raise RuntimeError("ACP runtimes are still starting")


async def _list_sessions(connection, observer):
    result, seen, cursors = [], set(), set()
    deadline = time.monotonic() + LIST_TIMEOUT
    cursor = None
    for _ in range(LIST_PAGES):
        async with asyncio.timeout(deadline - time.monotonic()):
            await connection.list_sessions(cursor=cursor)
        page = acp_history.sessions_page(observer.take("session/list"))
        for session in page.sessions:
            if session.id in seen:
                raise ValueError("Duplicate ACP session across pages")
            seen.add(session.id)
            result.append(session)
        cursor = page.next_cursor
        if cursor is None:
            return result
        if cursor in cursors or time.monotonic() > deadline:
            raise TimeoutError("ACP session listing did not complete")
        cursors.add(cursor)
    raise ValueError("ACP session list exceeded its page limit")

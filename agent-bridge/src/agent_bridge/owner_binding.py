"""Current root identity for one shared Bridge owner namespace."""

import fcntl
import json
import os
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from pathlib import Path

from .core import save, stamp

BACKENDS = {"codex", "claude", "agy", "opencode"}
_START_GUARD = ContextVar("agent_bridge_owner_start_guard", default=None)


class RootMismatch(RuntimeError):
    """A different known root currently owns this namespace."""


def identity():
    if os.environ.get("CLAUDECODE") == "1":
        backend, session = "claude", os.environ.get("CLAUDE_CODE_SESSION_ID")
    elif os.environ.get("CODEX_THREAD_ID"):
        backend, session = "codex", os.environ.get("CODEX_THREAD_ID")
    else:
        backend = os.environ.get("AGENT_BRIDGE_ROOT_HARNESS")
        session = os.environ.get("AGENT_BRIDGE_ROOT_SESSION")
    if (
        backend not in BACKENDS
        or not session
        or len(session) > 200
        or any(ord(char) < 32 for char in session)
    ):
        return None
    return {"backend": backend, "session_id": session}


def read(owner):
    path = Path(owner) / "root.json"
    if path.is_symlink():
        raise ValueError("unsafe root binding")
    try:
        if path.stat().st_size > 65536:
            raise ValueError("oversized root binding")
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    if type(data) is not dict:
        raise ValueError("invalid root binding")
    backend, session = data.get("backend"), data.get("session_id")
    if backend is None and session is None:
        return data
    if (
        type(backend) is not str
        or backend not in BACKENDS
        or type(session) is not str
        or not session
        or len(session) > 200
        or any(ord(char) < 32 for char in session)
    ):
        raise ValueError("invalid root binding identity")
    return data


def known(data):
    backend, session = data.get("backend"), data.get("session_id")
    return (
        {"backend": backend, "session_id": session}
        if type(backend) is str and backend in BACKENDS and type(session) is str and session
        else None
    )


def may_claim(data, current):
    bound = known(data)
    return bound is None or current is not None and bound == current


@contextmanager
def locked(owner):
    owner = Path(owner)
    owner.mkdir(mode=0o700, parents=True, exist_ok=True)
    if owner.is_symlink():
        raise ValueError("unsafe root owner")
    fd = os.open(owner / "root.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    released = False

    def release():
        nonlocal released
        if not released:
            # After fork, LOCK_UN would release the child's shared flock too.
            os.close(fd)
            released = True

    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield release
    finally:
        release()


@contextmanager
def guard(owner, current=None):
    with locked(owner):
        data = read(owner)
        bound = known(data)
        if bound and current and bound != current:
            raise RootMismatch(f"owner {Path(owner).name} belongs to another root; hand it off first")
        yield data


@contextmanager
def guard_many(owners, current=None):
    owners = sorted({Path(owner) for owner in owners})
    with ExitStack() as stack:
        for owner in owners:
            stack.enter_context(locked(owner))
        bindings = {owner: read(owner) for owner in owners}
        mismatched = [
            owner.name
            for owner, data in bindings.items()
            if known(data) and current and known(data) != current
        ]
        if mismatched:
            raise RootMismatch(f"owner {mismatched[0]} belongs to another root; hand it off first")
        yield bindings


def filter_owners(owners, jobs_root, current=None):
    owners = list(owners)
    names = sorted({value.split("/")[0] for value in owners})
    if current is None:
        return owners
    paths = {name: Path(jobs_root) / name for name in names}
    with guard_many(paths.values()) as bindings:
        visible = {
            name
            for name, owner in paths.items()
            if not known(bindings[owner]) or known(bindings[owner]) == current
        }
    return [value for value in owners if value.split("/")[0] in visible]


@contextmanager
def access(owner, current=None, takeover=False, start=False):
    """Lock a root-owned operation and refresh or explicitly transfer its binding."""
    with locked(owner) as release:
        data = read(owner)
        bound = known(data)
        if takeover and current is None:
            raise RuntimeError("handoff requires a known root session")
        if bound and current and bound != current and not takeover:
            raise RootMismatch(f"owner {Path(owner).name} belongs to another root; run handoff")
        if current is not None:
            data.update(at=stamp(), harness=current["backend"], **current)
            save(Path(owner) / "root.json", data)
        elif bound is None:
            data.update(at=stamp(), harness="unknown")
            save(Path(owner) / "root.json", data)
        token = _START_GUARD.set(release) if start else None
        try:
            yield
        finally:
            if token is not None:
                _START_GUARD.reset(token)


def release_start_guard():
    """Release the root namespace once the backend runner process has started."""
    release = _START_GUARD.get()
    if release is not None:
        release()


def record(owner, current=None):
    with access(owner, current):
        pass


def handoff(owner, current=None):
    with access(owner, current, takeover=True):
        pass

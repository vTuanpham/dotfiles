"""Registry and link lifecycle; native foreground sessions handle route teardown."""

import fcntl
import json
import os
import stat
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

import segno

from . import backend
from .models import Link, decode_link, loads, name, port, target


def default_state():
    base = Path(os.environ.get("XDG_STATE_HOME", ""))
    return (base if base.is_absolute() else Path.home() / ".local/state") / "portlink"


def private_fd(path, flags):
    fd = os.open(path, flags | os.O_NOFOLLOW, 0o600)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        os.close(fd)
        raise ValueError("Preview state files must be private and owned by you")
    return fd


class Store:
    def __init__(self, root=None):
        self.root = Path(root) if root is not None else default_state()

    @contextmanager
    def locked(self):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        info = self.root.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("Preview state directory must be private and owned by you")
        with os.fdopen(private_fd(self.root / ".lock", os.O_CREAT | os.O_RDWR), "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def records(self):
        out = []
        for path in self.root.glob("*.json"):
            with os.fdopen(private_fd(path, os.O_RDONLY)) as stream:
                raw = stream.read(65537)
            if len(raw) > 65536:
                raise ValueError("Oversized preview record")
            link = decode_link(loads(raw))
            if path.name != f"{link.id}.json":
                raise ValueError("Preview filename does not match its identity")
            out.append(link)
        if len({link.name for link in out}) != len(out):
            raise ValueError("Duplicate preview names")
        return out

    def save(self, link):
        path = self.root / f"{link.id}.json"
        fd, pending = tempfile.mkstemp(dir=self.root, prefix=".pending-")
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump(link.encode(), stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.link(pending, path)  # Publish complete JSON without replacing an existing record.
        finally:
            Path(pending).unlink(missing_ok=True)

    def remove(self, link):
        for suffix in (".json", ".svg"):
            (self.root / (link.id + suffix)).unlink(missing_ok=True)

    def qr(self, link):
        return self.root / f"{link.id}.svg"

    def live(self):
        for pending in self.root.glob(".pending-*"):
            pending.unlink()  # Under the lock, these can only be abandoned startup writes.
        out = []
        for link in self.records():
            state = backend.unit(link)
            backend.check_owner(link, state)
            if state.loaded and state.active:
                out.append(link)
            else:
                backend.stop(link)
                self.remove(link)
        return out

    def open(self, value, label=None, listen=None, ttl=3600):
        destination = target(value)
        backend.backend_ready(destination)
        if ttl is not None and (type(ttl) is not int or ttl <= 0):
            raise ValueError("TTL must be positive, or use --keep")
        identity = uuid.uuid4().hex
        label = name(label if label is not None else "preview-" + identity[:8])
        with self.locked():
            if any(link.name == label for link in self.live()):
                raise ValueError("Name already in use; choose another name or close that preview")
            node = backend.hostname()
            view = backend.serve()
            listen = port(listen) if listen is not None else next(
                (number for number in range(18000, 65536) if number not in view.ports), None)
            if listen is None or listen in view.ports:
                raise ValueError("Preview port is occupied; existing routes were left unchanged")
            url = f"https://{node}" + (f":{listen}" if listen != 443 else "")
            created = time.time()
            link = Link(identity, label, url, destination, listen, created,
                        created + ttl if ttl is not None else None)
            self.save(link)  # A crash during startup leaves an identifiable, collectable record.
            try:
                with os.fdopen(private_fd(self.qr(link), os.O_CREAT | os.O_EXCL | os.O_WRONLY), "wb") as out:
                    segno.make_qr(url).save(out, kind="svg", scale=5, light="white")
                backend.start(link)
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    state = backend.unit(link)
                    backend.check_owner(link, state)
                    if not state.active:
                        raise RuntimeError("Preview failed to start; check the user journal and Serve access")
                    if backend.ready(link, backend.serve()):
                        return link
                    time.sleep(0.15)
                raise RuntimeError("Preview route did not become ready; check Tailscale HTTPS setup")
            except BaseException:
                backend.stop(link)
                self.remove(link)
                raise

    def list(self):
        with self.locked():
            return self.live()

    def close(self, label):
        name(label)
        with self.locked():
            link = next((item for item in self.records() if item.name == label), None)
            if link is None:
                raise ValueError("No preview with that name")
            backend.stop(link)
            self.remove(link)
            return link

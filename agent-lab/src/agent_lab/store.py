"""Workspace lifecycle. Only retired, expired, unleased workspaces can be removed."""

import json
import os
import re
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Generator
from uuid import uuid4

from .files import Busy, existing_dir, inspect_tree, lock, private_dir, private_file
from .models import ID, Actor, Record, Run, load


def now() -> datetime:
    return datetime.now(timezone.utc)


def default_root() -> Path:
    explicit = os.environ.get("AGENT_LAB_HOME")
    if explicit is not None:
        if not Path(explicit).is_absolute():
            raise ValueError("AGENT_LAB_HOME must be absolute")
        return Path(explicit)
    value = os.environ.get("XDG_STATE_HOME", "")
    base = Path(value) if value and Path(value).is_absolute() else Path.home() / ".local/state"
    return base / "agent-lab"


class Store:
    def __init__(self, root: Path | None = None):
        self.root = root if root is not None else default_root()
        if not self.root.is_absolute():
            raise ValueError("workspace root must be absolute")
        self.records = self.root / "records"
        self.workspaces = self.root / "workspaces"
        self.locks = self.root / "locks"

    @contextmanager
    def locked(self, *, read_only: bool = False) -> Generator[None, None, None]:
        for path in (self.root, self.records, self.workspaces, self.locks):
            (existing_dir if read_only else private_dir)(path)
        with lock(self.root / ".lock", blocking=True, read_only=read_only):
            yield

    def directory(self, identifier: str) -> Path:
        if not ID.fullmatch(identifier):
            raise ValueError("invalid workspace ID; use agent-lab list")
        return self.workspaces / identifier

    def read(self, identifier: str) -> Record:
        self.directory(identifier)
        with private_file(self.records / f"{identifier}.json", os.O_RDONLY) as fd:
            raw = os.read(fd, 65537)
        if len(raw) > 65536:
            raise ValueError("registry record is too large")
        result = load(raw.decode("utf-8"))
        if result.id != identifier:
            raise ValueError("registry ID does not match its filename")
        return result

    def all(self) -> list[Record]:
        return [self.read(path.stem) for path in sorted(self.records.glob("*.json"))]

    def save(self, record: Record) -> None:
        Record.decode(record.to_dict())
        raw = json.dumps(record.to_dict(), ensure_ascii=False) + "\n"
        if len(raw.encode("utf-8")) > 65536:
            raise ValueError("registry record is too large")
        fd, pending = tempfile.mkstemp(prefix=".record-", dir=self.records)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(pending, self.records / f"{record.id}.json")
        finally:
            Path(pending).unlink(missing_ok=True)

    def create(self, name: str, purpose: str, actor: Actor) -> Record:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", name):
            raise ValueError(
                "name must be 1–48 lowercase letters, digits or hyphens, starting with a letter/digit"
            )
        instant = now().isoformat()
        record = Record(1, f"{name}-{uuid4().hex[:12]}", purpose, instant, instant, actor)
        Record.decode(record.to_dict())
        path = self.directory(record.id)
        path.mkdir(mode=0o700)
        for name in ("work", "artifacts", "tmp"):
            (path / name).mkdir(mode=0o700)
        self.save(record)
        return record

    def change(self, identifier: str, action: str, *, days: int = 14, summary: str | None = None) -> Record:
        record = self.read(identifier)
        with lock(self.locks / identifier):
            instant = now()
            if action == "retire":
                if record.kept:
                    raise ValueError("workspace is kept; restore it before retiring")
                if record.retired_at is not None:
                    return record
                if type(days) is not int or not 1 <= days <= 3650:
                    raise ValueError("retirement days must be between 1 and 3650")
                record = replace(
                    record,
                    retired_at=instant.isoformat(),
                    purge_after=(instant + timedelta(days=days)).isoformat(),
                    summary=summary,
                )
            elif action == "restore":
                record = replace(record, retired_at=None, purge_after=None, kept=False)
            elif action == "keep":
                record = replace(record, retired_at=None, purge_after=None, kept=True)
            else:
                raise ValueError("unknown workspace action")
            existing_dir(self.directory(identifier))
            record = replace(record, updated_at=instant.isoformat())
            self.save(record)
        return record

    def running(self, identifier: str) -> bool:
        try:
            with lock(self.locks / identifier, read_only=True):
                return False
        except FileNotFoundError:
            return False
        except Busy:
            return True

    def run(self, identifier: str, command: list[str], actor: Actor) -> int:
        with self.locked():
            record = self.read(identifier)
            if record.retired_at is not None:
                raise ValueError("restore the retired workspace before running commands")
            path = self.directory(identifier)
            existing_dir(path)
            for name in ("work", "artifacts", "tmp"):
                private_dir(path / name)
            lease = lock(self.locks / identifier)
            fd = lease.__enter__()
            try:
                started = now().isoformat()
                self.save(replace(record, updated_at=started, last_run=Run(actor, started, None, None)))
            except BaseException:
                lease.__exit__(None, None, None)
                raise
        try:
            env = {
                **os.environ,
                "AGENT_LAB_ID": identifier,
                "AGENT_LAB_HOME": str(self.root),
                "AGENT_LAB_WORKSPACE": str(path),
                "AGENT_LAB_ARTIFACTS": str(path / "artifacts"),
                "AGENT_LAB_TMP": str(path / "tmp"),
                "TMPDIR": str(path / "tmp"),
            }
            code = 125
            try:
                result = subprocess.run(command, cwd=path / "work", env=env, pass_fds=(fd,))
                code = result.returncode if result.returncode >= 0 else 128 - result.returncode
                return code
            except FileNotFoundError:
                code = 127
                raise
            except PermissionError:
                code = 126
                raise
            except KeyboardInterrupt:
                code = 130
                raise
            finally:
                with self.locked():
                    current = self.read(identifier)
                    finished = now().isoformat()
                    self.save(
                        replace(current, updated_at=finished, last_run=Run(actor, started, finished, code))
                    )
        finally:
            lease.__exit__(None, None, None)

    def gc(self, *, apply: bool = False, at: datetime | None = None) -> list[dict]:
        instant = at if at is not None else now()
        results = []
        for record in self.all():
            if record.purge_after is None or datetime.fromisoformat(record.purge_after) > instant:
                continue
            try:
                with lock(self.locks / record.id):
                    path = self.directory(record.id)
                    inspect_tree(path, deleting=True)
                    if apply:
                        if not shutil.rmtree.avoids_symlink_attacks:
                            raise ValueError("safe directory removal is unsupported on this platform")
                        shutil.rmtree(path)
                        (self.records / f"{record.id}.json").unlink()
                        (self.locks / record.id).unlink(missing_ok=True)
                    results.append({"id": record.id, "action": "purged" if apply else "would-purge"})
            except (ValueError, OSError) as exc:
                results.append({"id": record.id, "action": "blocked", "reason": str(exc)})
        return results

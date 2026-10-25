"""Store a human supplied value in owner-only environment files."""

import json
import os
import re
import secrets
import stat
from datetime import UTC, datetime
from pathlib import Path

NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
VALUE = re.compile(r"^[A-Za-z0-9_.-]+$")


def targets(paths):
    result = [Path(os.path.abspath(Path(path).expanduser())) for path in paths]
    if not result or len(set(result)) != len(result):
        raise ValueError("give each target file once")
    for path in result:
        try:
            info = path.lstat()
        except FileNotFoundError:
            info = None
        if info and (not stat.S_ISREG(info.st_mode) or info.st_mode & 0o022):
            raise ValueError(f"refused unsafe target: {path}")
        if not path.parent.is_dir():
            raise ValueError(f"target directory does not exist: {path.parent}")
    return result


def store(name, value, paths, prefix=""):
    if not NAME.fullmatch(name):
        raise ValueError("variable name must match [A-Z][A-Z0-9_]*")
    if prefix and not VALUE.fullmatch(prefix):
        raise ValueError("prefix must contain only letters, numbers, underscore, dot or hyphen")
    if not VALUE.fullmatch(value) or not value.startswith(prefix):
        raise ValueError("value rejected: it must match [A-Za-z0-9_.-]+ and the requested prefix")

    paths = targets(paths)
    originals, updates = {}, {}
    for path in paths:
        try:
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        except FileNotFoundError:
            descriptor = None
        if descriptor is not None:
            with os.fdopen(descriptor, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o022:
                    raise ValueError(f"refused unsafe target: {path}")
                data = stream.read()
            originals[path] = data
            lines = data.decode("utf-8").splitlines()
        else:
            lines = []
        lines = [line for line in lines if not re.match(rf"^\s*(export\s+)?{re.escape(name)}=", line)]
        lines.append(f"{'export ' if path.suffix == '.sh' else ''}{name}={value}")
        updates[path] = ("\n".join(lines) + "\n").encode()

    backup = None
    if originals:
        root = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "backups/env-secrets"
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        root.chmod(0o700)
        backup = root / datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        backup.mkdir(mode=0o700)
        backup.chmod(0o700)
        origins = {}
        for index, (path, data) in enumerate(originals.items()):
            copy = backup / f"{index}-{path.name}"
            copy.write_bytes(data)
            copy.chmod(0o600)
            origins[copy.name] = str(path)
        info = backup / "origin.json"
        info.write_text(
            json.dumps({"restore": "copy each file back over its original path", "files": origins}, indent=2)
        )
        info.chmod(0o600)

    staged = []
    try:
        for path, data in updates.items():
            # Recheck before replacement; os.replace replaces a symlink itself and never follows it.
            targets([path])
            temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            staged.append((temporary, path))
        for temporary, path in staged:
            os.replace(temporary, path)
            path.chmod(0o600)
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)
    return backup

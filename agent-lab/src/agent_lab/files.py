"""Private state files and symlink-aware size/cleanup inspection."""

import fcntl
import os
import stat
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

TOTAL_WARNING = 1024**3
FILE_WARNING = 256 * 1024**2


class Busy(ValueError):
    """A live command holds the workspace lease."""


def private_dir(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    existing_dir(path)


def existing_dir(path: Path) -> None:
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError(f"expected an owner-only directory: {path}")


@contextmanager
def private_file(path: Path, flags: int) -> Generator[int, None, None]:
    fd = os.open(path, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError(f"expected an owner-only regular file: {path}")
        yield fd
    finally:
        os.close(fd)


@contextmanager
def lock(path: Path, *, blocking: bool = False, read_only: bool = False) -> Generator[int, None, None]:
    flags = os.O_RDONLY if read_only else os.O_RDWR | os.O_CREAT
    mode = fcntl.LOCK_SH if read_only else fcntl.LOCK_EX
    with private_file(path, flags) as fd:
        try:
            fcntl.flock(fd, mode | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError as exc:
            raise Busy("workspace is in use; retry after its command exits") from exc
        yield fd


def inspect_tree(path: Path, *, deleting: bool = False) -> dict:
    existing_dir(path)
    info = path.lstat()
    total, count, largest = 0, 0, (0, None)

    def failed(error: OSError) -> None:
        raise error

    for directory, dirs, files in os.walk(path, followlinks=False, onerror=failed):
        base = Path(directory)
        if deleting and (".git" in dirs or ".git" in files):
            raise ValueError("contains a Git checkout/worktree; use its native cleanup before GC")
        for name in dirs + files:
            entry = base / name
            status = entry.lstat()
            if deleting and (status.st_dev != info.st_dev or os.path.ismount(entry)):
                raise ValueError("contains a mount; unmount it before GC")
            if stat.S_ISREG(status.st_mode):
                total += status.st_size
                count += 1
                if status.st_size > largest[0]:
                    largest = (status.st_size, str(entry.relative_to(path)))
    if deleting and os.path.ismount(path):
        raise ValueError("workspace is a mount; unmount it before GC")
    warnings = []
    if total >= TOTAL_WARNING:
        warnings.append("workspace is at least 1 GiB")
    if largest[0] >= FILE_WARNING:
        warnings.append(f"file is at least 256 MiB: {largest[1]}")
    return {
        "bytes": total,
        "files": count,
        "largest_bytes": largest[0],
        "largest_path": largest[1],
        "warnings": warnings,
    }

"""Owner-scoped acknowledgement cursors; displaying an event never acknowledges it."""

import fcntl
import json
from contextlib import contextmanager

from .core import URGENT_KINDS, save


def urgent(event):
    return (event.get("level") == "urgent" or event.get("kind") in URGENT_KINDS
            or (event.get("kind") == "message"
                and str(event.get("text", "")).lstrip().upper().startswith("URGENT:")))


def read_owner(owner):
    try:
        data = json.loads((owner / "ack.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"version": 1, "jobs": {}}
    if (not isinstance(data, dict) or type(data.get("version")) is not int or data.get("version") != 1
            or not isinstance(data.get("jobs"), dict)
            or any(not isinstance(c, dict) or set(c) != {"log", "through", "seen", "completed"}
                   or not isinstance(c["log"], str)
                   or any(type(c[k]) is not int or c[k] < 0 for k in ("through", "seen", "completed"))
                   for c in data["jobs"].values())):
        raise ValueError("invalid owner ack.json")
    return data


def cursor_for(job, data):
    try:
        stat = (job / "live.jsonl").stat()
        identity, size = f"{stat.st_dev}:{stat.st_ino}", stat.st_size
    except FileNotFoundError:
        identity, size = "", 0
    cursor = data["jobs"].get(job.name)
    if (cursor is None or cursor["log"] != identity
            or max(cursor[k] for k in ("through", "seen", "completed")) > size):
        cursor = {"log": identity, "through": 0, "seen": 0, "completed": 0}
    return cursor


@contextmanager
def edit_cursor(job):
    with (job.parent / "ack.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = read_owner(job.parent)
        cursor = cursor_for(job, data)
        yield cursor
        data["jobs"][job.name] = cursor
        save(job.parent / "ack.json", data)


def event_lines(job, offset=0):
    """Yield complete JSON objects and their byte boundaries; retain partial lines."""
    try:
        with (job / "live.jsonl").open("rb") as stream:
            stream.seek(offset)
            while raw := stream.readline():
                if not raw.endswith(b"\n"):
                    break
                end = stream.tell()
                try:
                    event = json.loads(raw)
                except (ValueError, UnicodeDecodeError):
                    continue
                if isinstance(event, dict) and isinstance(event.get("kind"), str):
                    yield end, event
    except FileNotFoundError:
        return


def pending(job):
    cursor = cursor_for(job, read_owner(job.parent))
    return [(end, event) for end, event in event_lines(job, cursor["through"])
            if urgent(event) and not (event.get("kind") == "turn_completed" and end <= cursor["completed"])]


def displayed(job, end):
    with edit_cursor(job) as cursor:
        cursor["seen"] = max(cursor["seen"], end)


def acknowledge(job, completion=None):
    with edit_cursor(job) as cursor:
        if completion is None:
            cursor["through"] = max(cursor["through"], cursor["seen"])
        else:
            cursor["completed"] = max(cursor["completed"], completion)

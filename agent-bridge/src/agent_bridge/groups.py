"""Root-owned membership/policy, and atomic, persistent completion notification decisions."""

import fcntl
import hashlib
import json
import os
import re
import uuid
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, replace
from datetime import datetime, timezone

from . import core, owner_binding
from .heavy import write_state
from .status_inputs import timestamp
from .status_model import GroupNotice, WakeGroup, WakePolicy

DEFAULT_POLICY = WakePolicy()
MAX_REMINDER_BACKOFF_SECONDS = 31536000


def name(value):
    if type(value) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", value):
        raise ValueError("group and member names use 1–64 letters, digits, dots, underscores or hyphens")
    return value


def duration(value):
    if value == "off":
        return None
    match = re.fullmatch(r"([0-9]+)([smh])", value)
    if not match:
        raise ValueError("duration needs seconds, minutes or hours, such as 60s or 15m; or off")
    seconds = int(match[1]) * {"s": 1, "m": 60, "h": 3600}[match[2]]
    if not 0 <= seconds <= 31536000:
        raise ValueError("duration must be between zero and one year")
    return seconds


def require_root():
    if os.environ.get(core.WORKER_FLAG):
        raise RuntimeError("delegated workers cannot change group policies or membership")


@contextmanager
def locked(owner):
    owner.mkdir(mode=0o700, parents=True, exist_ok=True)
    if owner.is_symlink():
        raise ValueError("unsafe group owner")
    fd = os.open(owner / "groups.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def read_json(path):
    if path.is_symlink() or path.stat().st_size > 1048576:
        raise ValueError("unsafe or oversized group state")
    value = json.loads(path.read_text())
    if type(value) is not dict or type(value.get("version")) is not int or value["version"] != 1:
        raise ValueError("invalid group state version")
    return value


def decode_policy(raw):
    keys = set(WakePolicy.__dataclass_fields__)
    if (
        type(raw) is not dict
        or set(raw) != keys
        or raw["wake"] not in {"each", "all", "quiet"}
        or type(raw["repeat_reminders"]) is not bool
    ):
        raise ValueError("invalid wake policy")
    for key in ("settle_seconds", "remind_seconds", "max_wait_seconds"):
        value = raw[key]
        if value is None and key != "settle_seconds":
            continue
        if type(value) is not int or not 0 <= value <= 31536000:
            raise ValueError("invalid wake policy duration")
    if raw["max_wait_seconds"] is not None and raw["wake"] != "all":
        raise ValueError("max-wait applies only to all")
    return WakePolicy(**raw)


def settings(owner, errors):
    try:
        data = read_json(owner / "groups.json")
        if type(data.get("policies")) is not dict or type(data.get("members")) is not dict:
            raise ValueError("invalid group settings")
        for key, raw in data["policies"].items():
            name(key)
            decode_policy(raw)
        for key, row in data["members"].items():
            name(key)
            if type(row) is not dict or set(row) != {"group", "epoch", "at", "log", "offset"}:
                raise ValueError("invalid group membership")
            name(row["group"])
            if (
                type(row["epoch"]) is not str
                or not re.fullmatch(r"[a-f0-9]{32}", row["epoch"])
                or type(row["log"]) is not str
                or type(row["offset"]) is not int
                or row["offset"] < 0
            ):
                raise ValueError("invalid group member turn")
            timestamp(row["at"])
        return data
    except FileNotFoundError:
        pass
    except (OSError, ValueError, TypeError, KeyError):
        errors.append(f"{owner.name}: group policy unavailable; using each")
    return {"version": 1, "policies": {}, "members": {}}


def assignment(job, group, new_turn=False):
    path = job / "live.jsonl"
    stat = path.stat() if path.exists() else None
    return {
        "group": name(group),
        "epoch": uuid.uuid4().hex,
        "at": core.stamp(),
        "log": f"{stat.st_dev}:{stat.st_ino}" if stat else "",
        "offset": stat.st_size if stat and new_turn else 0,
    }


def assign(job, group, new_turn=False):
    require_root()
    with locked(job.parent):
        data = settings(job.parent, [])
        previous = data["members"].get(job.name)
        if group is None:
            data["members"].pop(job.name, None)
        elif new_turn or previous is None or previous["group"] != group:
            data["members"][name(job.name)] = assignment(job, group, new_turn)
        write_state(job.parent / "groups.json", data)


def configure(owner, group, policy, members=()):
    require_root()
    name(group)
    decode_policy(asdict(policy))
    with locked(owner):
        data = settings(owner, [])
        data["policies"][group] = asdict(policy)
        for member in members:
            name(member)
            old = data["members"].get(member)
            if old is None or old["group"] != group:
                data["members"][member] = assignment(owner / member, group)
        write_state(owner / "groups.json", data)


def clear(owner, group):
    require_root()
    with locked(owner):
        data = settings(owner, [])
        data["policies"].pop(name(group), None)
        write_state(owner / "groups.json", data)


def ledger(owner):
    try:
        data = read_json(owner / "group-wakes.json")
    except FileNotFoundError:
        return {"version": 1, "handled": [], "all_batches": [], "reminded": {}, "notices": [], "oom": {}}
    if set(data) != {"version", "handled", "all_batches", "reminded", "notices", "oom"}:
        raise ValueError("invalid group wake ledger")
    for key in ("handled", "all_batches"):
        if type(data[key]) is not list or any(type(v) is not str for v in data[key]):
            raise ValueError("invalid group wake cursor")
    if (
        type(data["reminded"]) is not dict
        or type(data["oom"]) is not dict
        or type(data["notices"]) is not list
    ):
        raise ValueError("invalid group wake records")
    for key, row in data["reminded"].items():
        if (
            type(key) is not str
            or type(row) is not dict
            or set(row) != {"at", "count"}
            or type(row["count"]) is not int
            or not 1 <= row["count"] <= 32
        ):
            raise ValueError("invalid reminder cursor")
        timestamp(row["at"])
    for key, total in data["oom"].items():
        if type(key) is not str or type(total) is not int or total < 0:
            raise ValueError("invalid OOM wake cursor")
    data["notices"] = [decode_notice(row) for row in data["notices"]]
    return data


def decode_notice(raw):
    if type(raw) is not dict or set(raw) != set(GroupNotice.__dataclass_fields__):
        raise ValueError("invalid group notice")
    for key in ("id", "job", "kind", "at", "text", "status", "error", "owner"):
        if type(raw[key]) is not str:
            raise ValueError("invalid group notice field")
    timestamp(raw["at"])
    if raw["group"] is not None:
        name(raw["group"])
    if type(raw["offset"]) is not int or raw["offset"] != 0:
        raise ValueError("invalid group notice offset")
    for key in ("wakes", "informational", "seen"):
        if type(raw[key]) is not bool:
            raise ValueError("invalid group notice flag")
    for key in ("jobs", "missing", "completion_ids"):
        if type(raw[key]) is not list or any(type(v) is not str for v in raw[key]):
            raise ValueError("invalid group notice members")
    return GroupNotice(**{**raw, **{k: tuple(raw[k]) for k in ("jobs", "missing", "completion_ids")}})


def write_ledger(owner, data):
    write_state(owner / "group-wakes.json", {**data, "notices": [asdict(n) for n in data["notices"]]})


def iso(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()


def digest(parts):
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()


def evaluate(owner, jobs, events, now, errors, persist=True):
    """One locked transaction creates each digest; no append/commit crash window."""
    if persist and not os.environ.get(core.WORKER_FLAG):
        with locked(owner):
            return evaluate_locked(owner, jobs, events, now, errors, True)
    return evaluate_locked(owner, jobs, events, now, errors, False)


def evaluate_locked(owner, jobs, events, now, errors, persist):
    config = settings(owner, errors)
    try:
        state = ledger(owner)
    except (OSError, ValueError, TypeError, KeyError):
        errors.append(f"{owner.name}: group wake ledger unavailable; completions wake immediately")
        return jobs, events, (), ()
    job_map = {j.id: j for j in jobs if not j.retired_at}
    pending = [
        e
        for e in events
        if e.kind == "turn_completed"
        and e.job in job_map
        and e.offset > max(job_map[e.job].acknowledged_through, job_map[e.job].completed_through)
    ]
    pending_ids = {
        e.id
        for e in events
        if e.job in job_map
        and e.offset > job_map[e.job].acknowledged_through
        and not (e.kind == "turn_completed" and e.offset <= job_map[e.job].completed_through)
    }
    handled = set(state["handled"])
    by_group = {}
    for j in job_map.values():
        membership = config["members"].get(j.name)
        by_group.setdefault(membership["group"] if membership else None, set()).add(j.id)
    for member, row in config["members"].items():
        if any(j.name == member and j.retired_at for j in jobs):
            continue
        by_group.setdefault(row["group"], set()).add(f"{owner.name}/{member}")
    notices = [
        n
        for n in state["notices"]
        if (not n.completion_ids and not n.seen) or any(i in pending_ids for i in n.completion_ids)
    ]

    def emit(group, kind, selected, missing=(), reason="", key=None):
        ids = tuple(sorted(e.id for e in selected))
        identifier = digest([owner.name, group, kind, key or ids])
        existing = next((n for n in notices if n.id == identifier), None)
        if existing:
            return existing
        names = tuple(sorted({e.job for e in selected}))
        lead = names[0] if names else next(iter(sorted(job_map)), f"{owner.name}/group")
        text = reason + "; results: " + (", ".join(names) or "none")
        if missing:
            text += "; missing: " + ", ".join(missing)
        n = GroupNotice(
            identifier,
            lead,
            0,
            kind,
            iso(now),
            text,
            "",
            "",
            True,
            False,
            owner.name,
            group,
            names,
            tuple(missing),
            ids,
            False,
        )
        notices.append(n)
        return n

    # Native critical events retain their own acknowledgement/replay semantics.
    critical = any(
        e.wakes
        and (
            e.kind != "turn_completed"
            or e.error
            or e.status.lower() == "failed"
            or e.status.lower().startswith("error")
        )
        and e.id in pending_ids
        for e in events
    )
    for j in job_map.values():
        old = state["oom"].get(j.id)
        if j.oom_kill is not None:
            if (old is not None and j.oom_kill > old) or (j.oom_kill_delta or 0) > 0:
                emit(None, "oom_kill", (), reason=f"OOM kill on {j.id}", key=[j.id, j.oom_kill])
                critical = True
            state["oom"][j.id] = j.oom_kill
    views = []
    for group, member_ids in sorted(by_group.items(), key=lambda pair: pair[0] or ""):
        policy = decode_policy(config["policies"][group]) if group in config["policies"] else DEFAULT_POLICY
        unread = [e for e in pending if e.job in member_ids]
        fresh = [e for e in unread if e.id not in handled]
        finished, results, epochs, began = set(), [], [], []
        for identifier in sorted(member_ids):
            member = config["members"].get(identifier.split("/")[-1])
            if member:
                began.append(timestamp(member["at"]))
            history = [e for e in events if e.job == identifier]
            last_start = next((e for e in reversed(history) if e.kind == "turn_started"), None)
            epochs.append(
                [
                    identifier,
                    member["epoch"] if member else "ungrouped",
                    last_start.id if last_start else None,
                ]
            )
            if last_start and last_start.at:
                began.append(timestamp(last_start.at))
            terminal = (
                next(
                    (
                        e
                        for e in reversed(history)
                        if e.kind in {"turn_completed", "turn_failed", "stopped"}
                        or e.kind == "error"
                        and not job_map.get(identifier, None).running
                    ),
                    None,
                )
                if identifier in job_map
                else None
            )
            started = max((e.offset for e in history if e.kind == "turn_started"), default=0)
            baseline = (
                (member["offset"] if member and member["log"] == job_map[identifier].log_identity else 0)
                if identifier in job_map
                else 0
            )
            if terminal and terminal.offset > baseline and terminal.offset >= started:
                finished.add(identifier)
                results.append(terminal)
        batch = digest([group, epochs])
        missing = tuple(sorted(member_ids - finished))
        first = min((timestamp(e.at) if e.at else now for e in fresh), default=now)
        settle_due = first + policy.settle_seconds if fresh and policy.wake == "each" else None
        max_due = (
            max(began, default=first) + policy.max_wait_seconds
            if policy.wake == "all" and policy.max_wait_seconds is not None
            else None
        )
        due_all = (
            policy.wake == "all"
            and batch not in state["all_batches"]
            and (not missing or max_due is not None and now >= max_due)
        )
        if critical and fresh:
            emit(group, "completion_batch", fresh, reason="urgent event; held results flushed")
            handled.update(e.id for e in fresh)
            if due_all:
                state["all_batches"].append(batch)
        elif due_all:
            emit(
                group,
                "group_partial" if missing else "completion_batch",
                results,
                missing,
                "max-wait reached" if missing else "all group members finished",
                key=batch,
            )
            state["all_batches"].append(batch)
            handled.update(e.id for e in unread)
        elif settle_due is not None and now >= settle_due:
            emit(group, "completion_batch", fresh, reason="completion settle window ended")
            handled.update(e.id for e in fresh)
        reminder_dates = []
        if policy.remind_seconds is not None:
            for e in unread:
                old = state["reminded"].get(e.id)
                if old is None:
                    reminder_dates.append((timestamp(e.at) if e.at else now) + policy.remind_seconds)
                elif policy.repeat_reminders:
                    reminder_dates.append(
                        timestamp(old["at"])
                        + min(MAX_REMINDER_BACKOFF_SECONDS, policy.remind_seconds * 2 ** old["count"])
                    )
            if reminder_dates and now >= min(reminder_dates):
                key = (
                    [e.id for e in unread],
                    max((state["reminded"].get(e.id, {}).get("count", 0) for e in unread), default=0),
                )
                emit(group, "completion_reminder", unread, reason="finished results remain unread", key=key)
                for e in unread:
                    count = state["reminded"].get(e.id, {}).get("count", 0)
                    state["reminded"][e.id] = {"at": iso(now), "count": min(32, count + 1)}
                reminder_dates = (
                    [now + min(MAX_REMINDER_BACKOFF_SECONDS,
                               policy.remind_seconds * 2 ** min(32, key[1] + 1))]
                    if policy.repeat_reminders
                    else []
                )
        views.append(
            WakeGroup(
                f"{owner.name}/{group or '@ungrouped'}",
                owner.name,
                group,
                policy,
                tuple(sorted(member_ids)),
                len(finished),
                len(member_ids),
                tuple(e.id for e in fresh if e.id not in handled),
                iso(min(reminder_dates)) if reminder_dates else None,
                iso(settle_due)
                if settle_due is not None and any(e.id not in handled for e in fresh)
                else None,
                iso(max_due) if max_due is not None else None,
            )
        )
    state.update(handled=sorted(handled), notices=notices)
    if persist:
        write_ledger(owner, state)
    native = [
        replace(e, wakes=False, informational=False)
        if e.kind == "turn_completed"
        and not (e.error or e.status.lower() == "failed" or e.status.lower().startswith("error"))
        else e
        for e in events
    ]
    # Pending reminders saved by older versions were marked informational.
    output = tuple(
        replace(n, wakes=(n.wakes or n.kind == "completion_reminder") and not n.seen)
        for n in notices
    )
    jobs = [replace(j, group=config["members"].get(j.name, {}).get("group")) for j in jobs]
    return jobs, native, tuple(views), output


def seen(owner, identifier):
    require_root()
    with locked(owner):
        data = ledger(owner)
        current = next((n for n in data["notices"] if n.id == identifier), None)
        if current is None or current.seen:
            return False
        data["notices"] = [replace(n, seen=True) if n.id == identifier else n for n in data["notices"]]
        write_ledger(owner, data)
        return True


def deliver(notices, callback, current=None, guard_owners=()):
    """Only successful delivery marks notices seen; crashes leave them pending."""
    require_root()
    owners = sorted({owner for owner, _ in notices})
    with owner_binding.guard_many([*owners, *guard_owners], current) as bindings:
        with ExitStack() as stack:
            for owner in owners:
                stack.enter_context(locked(owner))
            data = {owner: ledger(owner) for owner in owners}
            pending = {
                (owner, n.id) for owner, state in data.items() for n in state["notices"]
                if owner_binding.may_claim(bindings[owner], current)
                and not n.seen and (owner, n.id) in notices
            }
            if not pending:
                return False
            callback()
            for owner, state in data.items():
                state["notices"] = [
                    replace(n, seen=True) if (owner, n.id) in pending else n for n in state["notices"]
                ]
                write_ledger(owner, state)
            return True

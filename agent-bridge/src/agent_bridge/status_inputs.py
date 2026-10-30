"""Persisted status boundaries: invalid observations stay unknown, never guessed."""

import re
import subprocess
from datetime import datetime

from agent_accounts import providers
from agent_resources import resources

from . import agy
from .acknowledgements import INFORMATIONAL_ONLY_KINDS, event_lines, urgent
from .core import command_env, load_state, tree_size
from .status_model import MESSAGE_PREVIEW_LIMIT, Event, TidyItem


def timestamp(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", value
    ):
        raise ValueError("timestamp requires RFC3339 date, time and timezone")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("timestamp requires timezone")
    return parsed.timestamp()


class EventLog:
    """Decode each complete log record once; retain no native command output."""

    def __init__(self, job_id, identity):
        self.job_id, self.identity = job_id, identity
        self.offset = 0
        self.rows: list[tuple[dict, Event]] = []

    def read(self, job, errors):
        if (job / "live.jsonl").is_symlink():
            raise ValueError("unsafe job log")
        fields = {
            "at",
            "recorded_at",
            "kind",
            "text",
            "message",
            "question",
            "status",
            "error",
            "level",
            "blocking",
            "peerDirected",
            "source",
            "target",
            "file",
            "requestId",
            "size",
            "preview",
            "message_kind",
            "quietSeconds",
            "tool_use_id",
            "itemId",
            "stepId",
            "tool",
            "noticeId",
        }
        for end, raw in event_lines(job, self.offset):
            self.offset = end
            try:
                at = raw.get("at")
                if at is not None:
                    timestamp(at)
                if raw.get("recorded_at") is not None:
                    timestamp(raw["recorded_at"])
                for key in ("text", "message", "question", "status"):
                    if raw.get(key) is not None and type(raw[key]) is not str:
                        raise ValueError("invalid event field")
                for key in ("tool_use_id", "itemId", "stepId", "tool", "noticeId"):
                    if raw.get(key) is not None and (not isinstance(raw[key], str) or len(raw[key]) > 512):
                        raise ValueError("invalid tool identity")
                for key in ("file", "requestId"):
                    if raw.get(key) is not None and (
                        type(raw[key]) is not str or len(raw[key]) > 512
                    ):
                        raise ValueError("invalid message identity")
                if raw.get("size") is not None and (
                    type(raw["size"]) is not int or raw["size"] < 0
                ):
                    raise ValueError("invalid message size")
                if raw.get("peerDirected") is not None and type(raw["peerDirected"]) is not bool:
                    raise ValueError("invalid peer message direction")
                if raw.get("preview") is not None and (
                    type(raw["preview"]) is not str
                    or len(raw["preview"]) > MESSAGE_PREVIEW_LIMIT
                ):
                    raise ValueError("invalid message preview")
                text = raw.get("text") or raw.get("question") or raw.get("message") or ""
                event = Event(
                    f"{self.job_id}:{self.identity}:{end}",
                    self.job_id,
                    end,
                    raw["kind"],
                    at,
                    text,
                    raw.get("status") or "",
                    str(raw.get("error") or ""),
                    urgent(raw),
                    urgent(raw, True) or raw["kind"] in INFORMATIONAL_ONLY_KINDS,
                )
                self.rows.append(({k: v for k, v in raw.items() if k in fields}, event))
            except (ValueError, TypeError):
                errors.append(f"{self.job_id}: invalid event")


def read_job(job, root):
    path = job / "state.json"
    if (path.is_symlink() or job.is_symlink() or job.parent.is_symlink()
            or not path.resolve().is_relative_to(root.resolve()) or path.stat().st_size > 1048576):
        raise ValueError("unsafe or oversized job state")
    state = load_state(job)
    for key in (
        "backend",
        "title",
        "model",
        "effort",
        "account",
        "cwd",
        "memoryMax",
        "cpuQuota",
        "retiredAt",
        "purgeAfter",
    ):
        value = state.get(key)
        if value is not None and (
            type(value) is not str or len(value) > 4096 or any(ord(c) < 32 for c in value)
        ):
            raise ValueError("invalid job status field")
    if state.get("backend") not in (None, "codex", "agy", "claude", "opencode"):
        raise ValueError("invalid backend")
    pid = state.get("runnerPid")
    if pid is not None and (type(pid) is not int or pid < 1):
        raise ValueError("invalid runner PID")
    retry = state.get("retry")
    if retry is not None and (
        type(retry) is not dict
        or any(type(retry.get(key)) is not int or retry[key] < 1 for key in ("attempt", "maximum"))
        or retry["attempt"] > retry["maximum"]
    ):
        raise ValueError("invalid retry state")
    if state.get("memoryMax") is not None:
        resources.memory_size(state["memoryMax"])
    if state.get("cpuQuota") is not None:
        resources.cpu_size(state["cpuQuota"])
    for key in ("retiredAt", "purgeAfter"):
        if state.get(key) is not None:
            timestamp(state[key])
    if state.get("retiredAt") and (
        not state.get("purgeAfter") or timestamp(state["purgeAfter"]) < timestamp(state["retiredAt"])
    ):
        raise ValueError("invalid retirement dates")
    return state


def unanswered(job, evs):
    turns = [i for i, e in enumerate(evs) if e.get("kind") == "turn_completed"]
    start, end = (turns[-2] if len(turns) > 1 else -1), (turns[-1] if turns else len(evs) - 1)
    if list((job / "steer").glob("[0-9]*.md")):
        return 0
    blocking = [
        i
        for i in range(start + 1, end + 1)
        if evs[i].get("kind") in ("message", "question") and urgent(evs[i])
    ]
    if blocking and any(e.get("kind") == "stopped" for e in evs[blocking[-1] + 1 :]):
        return 0
    last = max(
        (i for i, e in enumerate(evs) if e.get("kind") in (
            "steer_sent", "root_steer", "question_answered"
        )),
        default=-1,
    )
    return sum(i > last for i in blocking)


def quotas(now, errors):
    result, failures = providers.snapshot(now, root=agy.ACCOUNTS, environ=command_env())
    errors.extend(failures)
    return result


def tidy(job, state, now):
    """Same conservative eligibility as purge: unreadable worktree means dirty."""
    wt = job / "out/wt"
    age = max(0, int((now - timestamp(state["retiredAt"])) / 86400))
    items = []
    if wt.is_symlink() or (job / "out").is_symlink():
        raise ValueError("unsafe worktree")
    if (wt / ".git").exists():
        run = subprocess.run(
            ["git", "--no-optional-locks", "-C", str(wt), "status", "--porcelain"],
            capture_output=True,
            timeout=10,
            env=command_env(),
        )
        dirty = run.returncode != 0 or bool(run.stdout)
        items.append(TidyItem("worktree", str(wt), job.parent.name, job.name, tree_size(wt), age, dirty))
        if dirty:
            return items
    items.append(TidyItem("job", str(job), job.parent.name, job.name, tree_size(job), age, None))
    return items

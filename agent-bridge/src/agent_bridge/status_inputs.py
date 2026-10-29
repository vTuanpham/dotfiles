"""Persisted status boundaries: invalid observations stay unknown, never guessed."""

import json
import re
import subprocess
from datetime import datetime

from . import agy, resources
from .acknowledgements import INFORMATIONAL_ONLY_KINDS, event_lines, urgent
from .core import command_env, load_state, tree_size
from .status_model import MESSAGE_PREVIEW_LIMIT, Event, Quota, QuotaWindow, TidyItem

AGY_QUOTA_FRESH_SECONDS = 600


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


def codex_quotas(text):
    """codex-auth's local cache view; strip account addresses at this boundary."""
    result = []
    for line in text.splitlines():
        match = re.fullmatch(r"\s*(\*)?\s*(\d{2})\s+\S+@\S+\s+(.*)", line)
        if not match:
            continue
        rest = match[3]
        plan = re.match(r"([A-Za-z][A-Za-z ]*?)\s{2,}", rest)
        if not plan:
            raise ValueError("invalid codex quota plan")
        plan = plan[1].strip()
        pcts = [int(p) for p in re.findall(r"(\d+)%", rest)]
        if any(p > 100 for p in pcts) or len(pcts) > 2:
            raise ValueError("invalid codex quota percentage")
        parts = []
        unsupported = False
        if pcts:
            if plan.lower().startswith("free"):
                parts = [("m", pcts[0])]
            elif plan.lower().startswith("plus"):
                parts = list(zip(("h", "w"), pcts))
            elif plan.lower().startswith("pro"):
                parts = [("w", pcts[-1])]
            else:
                unsupported = True
        status = (
            "expired" if "token_expired" in rest else "signed out" if re.search(r"\b401\b", rest) else None
        )
        if unsupported and status is None:
            status = "unsupported plan"
        result.append(
            Quota(
                "codex",
                match[2],
                plan,
                match[1] == "*",
                tuple(QuotaWindow(label, pct, "", label, None) for label, pct in parts),
                status,
                None,
                None,
                "unknown",
            )
        )
    return result


def agy_quota(data, now):
    if type(data) is not dict or type(data.get("account")) is not str or not data["account"]:
        raise ValueError("invalid quota account")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", data["account"]):
        raise ValueError("invalid quota account")
    at = timestamp(data.get("at"))
    if at > now + 60 or type(data.get("rows")) is not list or not data["rows"]:
        raise ValueError("invalid quota time or rows")
    parts = []
    groups = {"Gemini Models": "G", "Claude and GPT models": "C", "Gemini 4 Argon": "A"}
    for row in data["rows"]:
        if (
            type(row) is not dict
            or any(type(row.get(k)) is not str for k in ("group", "limit", "resets"))
            or type(row.get("remaining")) is not int
            or not 0 <= row["remaining"] <= 100
        ):
            raise ValueError("invalid quota row")
        if any(len(row[k]) > 4096 or any(ord(c) < 32 for c in row[k]) for k in ("group", "limit", "resets")):
            raise ValueError("invalid quota row text")
        label = groups.get(row["group"], row["group"])
        if "five hour" in row["limit"].lower():
            label += "h"
        elif "weekly" in row["limit"].lower():
            label += "w"
        else:
            label += "/" + row["limit"]  # preserve unknown limits rather than invent a weekly window
        parts.append(QuotaWindow(label, row["remaining"], row["group"], row["limit"], row["resets"]))
    order = list(dict.fromkeys(p.label[0] for p in parts))
    parts.sort(key=lambda p: (order.index(p.label[0]), p.label))
    age = max(0, int(now - at))
    return Quota(
        "agy",
        data["account"],
        None,
        False,
        tuple(parts),
        None,
        data["at"],
        age,
        "fresh" if age <= AGY_QUOTA_FRESH_SECONDS else "stale",
    )


def quotas(now, errors):
    result = []
    try:
        run = subprocess.run(
            ["codex-auth", "list"], capture_output=True, text=True, timeout=5, env=command_env()
        )
        if run.returncode == 0:
            result.extend(codex_quotas(run.stdout))
        else:
            errors.append("codex quota unavailable")
    except (OSError, ValueError, subprocess.SubprocessError):
        errors.append("codex quota unavailable")
    for path in sorted(agy.ACCOUNTS.glob("*/quota.json")):
        try:
            if (path.is_symlink() or not path.resolve().is_relative_to(agy.ACCOUNTS.resolve())
                    or path.stat().st_size > 1048576):
                raise ValueError("unsafe quota cache")
            q = agy_quota(json.loads(path.read_text()), now)
            if q.account != path.parent.name:
                raise ValueError("quota account mismatch")
            result.append(q)
        except (OSError, ValueError, TypeError):
            errors.append("agy quota cache invalid")
    return tuple(result)


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

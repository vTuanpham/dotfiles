"""Decode provider observations once; missing freshness stays unknown."""

import math
import re

from .models import Quota, QuotaWindow, timestamp

AGY_QUOTA_FRESH_SECONDS = 600
CLAUDE_QUOTA_FRESH_SECONDS = 600


def claude_quotas(data, now):
    """cswap JSON v1 reports percent used; shared observations report remaining."""
    if (type(data) is not dict or type(data.get("schemaVersion")) is not int
            or data["schemaVersion"] != 1 or "activeAccountNumber" not in data
            or type(data.get("accounts")) is not list):
        raise ValueError("invalid Claude account document")
    active = data.get("activeAccountNumber")
    if active is not None and (type(active) is not int or active < 1):
        raise ValueError("invalid Claude active account")
    result, seen = [], set()
    for row in data["accounts"]:
        if type(row) is not dict or type(row.get("number")) is not int or row["number"] < 1:
            raise ValueError("invalid Claude account number")
        number = row["number"]
        if number in seen or type(row.get("active")) is not bool or row["active"] != (active == number):
            raise ValueError("inconsistent Claude account identity")
        seen.add(number)
        status = row.get("usageStatus")
        if (type(status) is not str or not re.fullmatch(r"[a-z_]{1,64}", status)
                or type(row.get("disabled", False)) is not bool):
            raise ValueError("invalid Claude account status")
        observed = row.get("usageFetchedAt")
        at = timestamp(observed) if observed is not None else None
        if at is not None and at > now + 60:
            raise ValueError("invalid Claude observation time")
        age = max(0, int(now - at)) if at is not None else None
        freshness = ("unknown" if age is None else
                     "fresh" if age <= CLAUDE_QUOTA_FRESH_SECONDS else "stale")
        windows = []
        usage = row.get("usage")
        if status == "ok":
            if type(usage) is not dict:
                raise ValueError("missing Claude usage")
            scoped = usage.get("scoped", [])
            if type(scoped) is not list:
                raise ValueError("invalid Claude model windows")
            entries = [(key, label, "", limit, usage[key]) for key, label, limit in
                       (("fiveHour", "h", "five hour"), ("sevenDay", "w", "weekly")) if key in usage]
            for window in scoped:
                if (type(window) is not dict or type(window.get("name")) is not str
                        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._/-]{0,63}", window["name"])):
                    raise ValueError("invalid Claude model name")
                entries.append(("scoped", window["name"] + "w", window["name"], "weekly", window))
            for _, label, group, limit, window in entries:
                if type(window) is not dict:
                    raise ValueError("invalid Claude quota window")
                used = window.get("pct")
                if (type(used) not in (int, float) or used < 0
                        or (type(used) is float and not math.isfinite(used))):
                    raise ValueError("invalid Claude usage percentage")
                resets = window.get("resetsAt")
                if resets is not None and timestamp(resets) <= now:
                    freshness = "stale"
                    continue
                windows.append(QuotaWindow(label, math.floor(max(0, 100 - used)), group, limit, resets))
        elif usage is not None:
            raise ValueError("unavailable Claude account carries actionable usage")
        state = ("disabled" if row.get("disabled", False) else
                 None if status == "ok" else status.replace("_", " "))
        if not windows and state is None:
            state = "usage unknown"
        result.append(Quota("claude", f"{number:02d}", None, row["active"], tuple(windows),
                            state, observed, age, freshness))
    if active is not None and active not in seen:
        raise ValueError("Claude active account is absent")
    return tuple(result)


def codex_quotas(text):
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
        parts, unsupported = [], False
        if pcts:
            if plan.lower().startswith("free"):
                parts = [("m", pcts[0])]
            elif plan.lower().startswith("plus"):
                parts = list(zip(("h", "w"), pcts))
            elif plan.lower().startswith("pro"):
                parts = [("w", pcts[-1])]
            else:
                unsupported = True
        status = ("expired" if "token_expired" in rest else
                  "signed out" if re.search(r"\b401\b", rest) else None)
        if unsupported and status is None:
            status = "unsupported plan"
        result.append(Quota("codex", match[2], plan, match[1] == "*",
                            tuple(QuotaWindow(label, pct, "", label, None) for label, pct in parts),
                            status, None, None, "unknown"))
    return result


def agy_quota(data, now):
    if (type(data) is not dict or type(data.get("account")) is not str
            or not re.fullmatch(r"[A-Za-z0-9_-]+", data["account"])):
        raise ValueError("invalid quota account")
    at = timestamp(data.get("at"))
    if at > now + 60 or type(data.get("rows")) is not list or not data["rows"]:
        raise ValueError("invalid quota time or rows")
    parts = []
    groups = {"Gemini Models": "G", "Claude and GPT models": "C", "Gemini 4 Argon": "A"}
    for row in data["rows"]:
        if (type(row) is not dict
                or any(type(row.get(k)) is not str for k in ("group", "limit", "resets"))
                or type(row.get("remaining")) is not int or not 0 <= row["remaining"] <= 100):
            raise ValueError("invalid quota row")
        if any(len(row[k]) > 4096 or any(ord(c) < 32 for c in row[k])
               for k in ("group", "limit", "resets")):
            raise ValueError("invalid quota row text")
        label = groups.get(row["group"], row["group"])
        if "five hour" in row["limit"].lower():
            label += "h"
        elif "weekly" in row["limit"].lower():
            label += "w"
        else:
            label += "/" + row["limit"]
        parts.append(QuotaWindow(label, row["remaining"], row["group"], row["limit"], row["resets"]))
    order = list(dict.fromkeys(p.label[0] for p in parts))
    parts.sort(key=lambda p: (order.index(p.label[0]), p.label))
    age = max(0, int(now - at))
    return Quota("agy", data["account"], None, False, tuple(parts), None, data["at"], age,
                 "fresh" if age <= AGY_QUOTA_FRESH_SECONDS else "stale")

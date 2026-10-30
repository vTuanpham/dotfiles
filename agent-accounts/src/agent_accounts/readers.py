"""Decode provider observations once; missing freshness stays unknown."""

import re

from .models import Quota, QuotaWindow, timestamp

AGY_QUOTA_FRESH_SECONDS = 600


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

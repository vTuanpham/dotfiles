import copy
import json
import subprocess
from datetime import datetime, timezone

import pytest

from agent_accounts import providers
from agent_accounts.readers import claude_quotas

AT = "2026-10-30T10:00:00Z"
RESET = "2026-10-31T10:00:00Z"
NOW = datetime.fromisoformat(AT).timestamp()


def document():
    return {"schemaVersion": 1, "activeAccountNumber": 1, "accounts": [
        {"number": 1, "active": True, "email": "account@example.invalid", "alias": "private alias",
         "usageStatus": "ok", "usageFetchedAt": AT, "usage": {
             "fiveHour": {"pct": 25.2, "resetsAt": RESET},
             "sevenDay": {"pct": 100, "resetsAt": RESET},
             "scoped": [{"name": "Opus", "pct": 40, "resetsAt": RESET}]}},
        {"number": 2, "active": False, "usageStatus": "token_expired", "usage": None,
         "lastGoodUsage": {"fiveHour": {"pct": 0}}},
    ]}


def test_used_percent_becomes_conservative_remaining_with_account_and_freshness():
    rows = claude_quotas(document(), NOW)
    assert rows[0].account == "01" and rows[0].active and rows[0].freshness == "fresh"
    assert [(w.label, w.remaining_percent) for w in rows[0].windows] == [("h", 74), ("w", 0), ("Opusw", 60)]
    assert rows[1].windows == () and rows[1].status == "token expired"
    assert rows[1].freshness == "unknown"
    assert "example.invalid" not in repr(rows) and "private alias" not in repr(rows)


@pytest.mark.parametrize("used", [True, -1, "25", None, float("nan"), float("inf")])
def test_invalid_usage_is_never_reported_as_available(used):
    data = document()
    data["accounts"][0]["usage"]["fiveHour"]["pct"] = used
    with pytest.raises(ValueError):
        claude_quotas(data, NOW)


@pytest.mark.parametrize("used", [100.1, 101, 10**1000])
def test_over_limit_usage_is_zero_remaining_without_losing_other_accounts(used):
    data = document()
    data["accounts"][0]["usage"]["fiveHour"]["pct"] = used
    rows = claude_quotas(data, NOW)
    assert rows[0].windows[0].remaining_percent == 0 and len(rows) == 2


@pytest.mark.parametrize("change", [
    lambda d: d.update(schemaVersion=True),
    lambda d: d.update(activeAccountNumber=3),
    lambda d: d["accounts"].append(copy.deepcopy(d["accounts"][0])),
    lambda d: d["accounts"][0].update(active=False),
    lambda d: d["accounts"][0].update(usageFetchedAt="2026-10-30T10:02:00Z"),
    lambda d: d["accounts"][0].update(usageFetchedAt="2026-10-30T10:00:00"),
    lambda d: d["accounts"][0]["usage"]["scoped"][0].update(name="bad\x1b[31m"),
])
def test_identity_time_and_terminal_control_corruption_are_rejected(change):
    data = document()
    change(data)
    with pytest.raises(ValueError):
        claude_quotas(data, NOW)


def test_expired_and_missing_windows_do_not_turn_into_full_quota():
    data = document()
    data["accounts"][0]["usage"] = {"fiveHour": {"pct": 0, "resetsAt": AT}}
    quota = claude_quotas(data, NOW)[0]
    assert quota.windows == () and quota.freshness == "stale" and quota.status == "usage unknown"
    data["accounts"][0]["usage"] = {}
    assert claude_quotas(data, NOW)[0].windows == ()
    data["accounts"][0]["usage"] = {"fiveHour": {"pct": 50}}
    data["accounts"][0].pop("usageFetchedAt")
    assert claude_quotas(data, NOW)[0].freshness == "unknown"


def test_disabled_and_stale_accounts_keep_their_state():
    data = document()
    data["accounts"][0]["disabled"] = True
    row = claude_quotas(data, NOW + 601)[0]
    assert row.status == "disabled" and row.freshness == "stale" and row.age_seconds == 601


def test_refresh_persists_only_public_allowance_fields_and_snapshot_is_offline(tmp_path, monkeypatch):
    cache = providers.CLAUDE_CACHE
    data = document()
    data["accounts"][0]["usageFetchedAt"] = datetime.now(timezone.utc).isoformat()
    data["accounts"][0]["usage"]["fiveHour"]["vendorSecret"] = "must not persist"
    data["accounts"][0]["vendorSecret"] = "must not persist"
    monkeypatch.setattr(providers.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a, 0, json.dumps(data), "private stderr"))
    providers.refresh_claude()
    saved = cache.read_text()
    assert all(value not in saved for value in
               ("example.invalid", "private alias", "vendorSecret", "must not persist"))
    assert cache.stat().st_mode & 0o777 == 0o600
    assert cache.parent.stat().st_mode & 0o777 == 0o700
    calls = []

    def local_only(args, **kwargs):
        calls.append(args)
        assert args == ["codex-auth", "list", "--skip-api"]
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(providers.subprocess, "run", local_only)
    rows, errors = providers.snapshot(root=tmp_path / "agy")
    assert errors == [] and len(rows) == 2 and rows[0].backend == "claude"
    assert len(calls) == 1


@pytest.mark.parametrize("output", ["not JSON", '{"schemaVersion":1,"accounts":[],"accounts":[]}',
                                   '{"schemaVersion":2,"accounts":[]}'])
def test_bad_refresh_preserves_previous_cache(output, monkeypatch):
    cache = providers.CLAUDE_CACHE
    cache.parent.mkdir()
    cache.write_text("previous")
    monkeypatch.setattr(providers.subprocess, "run", lambda *a, **k:
                        subprocess.CompletedProcess(a, 0, output, ""))
    with pytest.raises(ValueError):
        providers.refresh_claude()
    assert cache.read_text() == "previous"


def test_invalid_claude_cache_does_not_hide_other_providers(tmp_path, monkeypatch):
    cache = providers.CLAUDE_CACHE
    cache.parent.mkdir()
    cache.write_text("broken")
    monkeypatch.setattr(providers.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a, 0, "* 01 account@example.invalid  Plus      0  62%  81%  Now", ""))
    rows, errors = providers.snapshot(root=tmp_path / "agy")
    assert len(rows) == 1 and rows[0].backend == "codex"
    assert errors == ["claude quota cache invalid"]

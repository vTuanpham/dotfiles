import json
import subprocess
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from agent_accounts import providers
from agent_accounts.readers import agy_quota, codex_quotas


def test_codex_cache_keeps_alias_and_unknown_freshness_without_address():
    rows = codex_quotas("* 03 account@example.invalid  Plus      0  62%  81%  Now")
    assert len(rows) == 1 and rows[0].account == "03" and rows[0].active
    assert rows[0].freshness == "unknown" and rows[0].observed_at is None
    assert [window.remaining_percent for window in rows[0].windows] == [62, 81]
    assert "example.invalid" not in repr(rows)


@pytest.mark.parametrize("remaining", [True, -1, 101, "40"])
def test_invalid_observation_never_becomes_quota(remaining):
    data = {"account": "a1", "at": datetime.now(timezone.utc).isoformat(),
            "rows": [{"group": "Gemini Models", "limit": "weekly", "remaining": remaining,
                      "resets": "tomorrow"}]}
    with pytest.raises(ValueError):
        agy_quota(data, datetime.now(timezone.utc).timestamp())


def test_account_refresh_requires_existing_auth_and_keeps_cache_on_invalid_response(tmp_path, monkeypatch):
    account = tmp_path / "a1"
    account.mkdir()
    cache = account / "quota.json"
    cache.write_text("previous cache")
    calls = []

    def run(*args, **kwargs):
        calls.append(kwargs["env"])
        return SimpleNamespace(returncode=0, stdout='{"response":"invalid usage"}')

    monkeypatch.setattr(providers.subprocess, "run", run)
    with pytest.raises(ValueError, match="signed in"):
        providers.refresh("a1", root=tmp_path)
    assert calls == []
    token = account / providers.TOKEN
    token.parent.mkdir(parents=True)
    token.write_text("synthetic")
    with pytest.raises(ValueError):
        providers.refresh("a1", root=tmp_path)
    assert cache.read_text() == "previous cache"


def test_cached_inventory_needs_no_bridge_or_job_state(tmp_path, monkeypatch):
    monkeypatch.setattr(providers.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a, 0, "  01 account@example.invalid  Pro      0  71%  Now", ""))
    rows, errors = providers.snapshot(root=tmp_path)
    assert errors == [] and len(rows) == 1 and rows[0].backend == "codex"
    assert rows[0].windows[0].remaining_percent == 71


def test_explicit_refresh_atomically_writes_private_validated_observation(tmp_path, monkeypatch):
    token = tmp_path / "a1" / providers.TOKEN
    token.parent.mkdir(parents=True)
    token.write_text("synthetic")
    monkeypatch.setattr(providers.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a, 0, '{"response":"Gemini Models\\tweekly\\t90%\\ttomorrow"}', ""))
    observation = providers.refresh("a1", root=tmp_path)
    cache = tmp_path / "a1/quota.json"
    assert observation.freshness == "fresh" and observation.account == "a1"
    assert json.loads(cache.read_text())["rows"][0]["remaining"] == 90
    assert cache.stat().st_mode & 0o777 == 0o600

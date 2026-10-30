import pytest

from agent_accounts import providers


@pytest.fixture(autouse=True)
def isolate_claude_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(providers, "CLAUDE_CACHE", tmp_path / "state/claude.json")

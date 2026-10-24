import pytest


@pytest.fixture(autouse=True)
def isolated_launcher_inventory(monkeypatch):
    # Unit fixtures must not inspect the developer's real launcher jobs.
    monkeypatch.setattr("agent_inbox.catalog.read", lambda: {})

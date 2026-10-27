import pytest

from agent_bridge import core


@pytest.fixture(autouse=True)
def isolated_bridge_environment(monkeypatch, tmp_path):
    # Tests launched inside a worker must never inspect or clean its live queue/state.
    monkeypatch.delenv("AGENT_BRIDGE_WORKER", raising=False)
    monkeypatch.delenv("AGENT_BRIDGE_JOB", raising=False)
    monkeypatch.setenv("AGENT_BRIDGE_HEAVY_DIR", str(tmp_path / "heavy"))
    monkeypatch.setattr(core, "JOBS", tmp_path / "jobs")

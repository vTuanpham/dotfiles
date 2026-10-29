import os
import stat

import pytest

from agent_bridge import core, groups
from agent_bridge.status_model import WakePolicy


@pytest.fixture(autouse=True)
def isolated_bridge_environment(monkeypatch, tmp_path):
    # Tests launched inside a worker must never inspect or clean its live queue/state.
    monkeypatch.delenv("AGENT_BRIDGE_WORKER", raising=False)
    monkeypatch.delenv("AGENT_BRIDGE_JOB", raising=False)
    for name in ("CODEX_THREAD_ID", "CLAUDECODE", "CLAUDE_CODE_SESSION_ID",
                 "AGENT_BRIDGE_ROOT_HARNESS", "AGENT_BRIDGE_ROOT_SESSION"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AGENT_BRIDGE_HEAVY_DIR", str(tmp_path / "heavy"))
    monkeypatch.setattr(core, "JOBS", tmp_path / "jobs")
    # Existing lifecycle tests use immediate completions; policy tests exercise the production settle window.
    monkeypatch.setattr(groups, "DEFAULT_POLICY", WakePolicy(settle_seconds=0))


@pytest.fixture(autouse=True)
def never_run_the_real_agy(tmp_path_factory, monkeypatch):
    """A test that reaches the agy CLI would open a Google sign-in browser on the owner's desktop."""
    stub = tmp_path_factory.mktemp("agy-stub") / "agy"
    stub.write_text("#!/bin/sh\necho 'tests must not run the real agy CLI' >&2\nexit 97\n")
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{stub.parent}{os.pathsep}{os.environ.get('PATH', '')}")

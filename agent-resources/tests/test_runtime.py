import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from agent_resources import control, heavy


def test_standalone_exec_preserves_environment_argv_stdin_and_exit(tmp_path):
    env = {"PATH": os.defpath, "HOME": str(tmp_path),
           "PYTHONPATH": str(Path(heavy.__file__).parents[1]),
           "AGENT_RESOURCES_HOME": str(tmp_path / "queue"), "AGENT_RESOURCES_MIN_AVAILABLE_MIB": "0",
           "AGENT_RESOURCES_MAX_LOAD": "1000000", "JOB_API_KEY": "synthetic-value"}
    script = ("import json,os,sys; "
              "print(json.dumps([os.environ['JOB_API_KEY'],sys.argv[1],sys.stdin.read()])); sys.exit(7)")
    result = subprocess.run([sys.executable, "-m", "agent_resources.cli", "run", "--mem", "1M", "--",
                             sys.executable, "-c", script, "$literal"], env=env, input="stdin payload",
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 7
    assert json.loads(result.stdout) == ["synthetic-value", "$literal", "stdin payload"]


def test_controller_identity_blocks_foreign_root_before_cancelling(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_RESOURCES_HOME", str(tmp_path / "queue"))
    monkeypatch.setenv("CODEX_THREAD_ID", "foreign-root")
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.delenv("AGENT_RESOURCES_OWNER", raising=False)
    folder = heavy.prepare()
    request = folder / "000-abc.request"
    row = {"job": "group/job", "owner": "codex:original-root", "running": False}
    monkeypatch.setattr(heavy, "entries", lambda _: [(request, row)])
    monkeypatch.setattr(heavy, "write_state", lambda *_: pytest.fail("foreign root mutated request"))
    with pytest.raises(RuntimeError, match="different root"):
        control.cancel("abc")


def test_worker_cannot_control_queue(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_RESOURCES_HOME", str(tmp_path / "queue"))
    monkeypatch.setenv("AGENT_RESOURCES_WORKER", "1")
    with pytest.raises(RuntimeError, match="workers cannot control"):
        control.listing()
    assert not (tmp_path / "queue").exists()


def test_requested_scope_cap_is_required(monkeypatch):
    monkeypatch.setattr(heavy.shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError, match="cannot be applied"):
        heavy.scope_prefix("10")

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_bridge import agy, claude, codex, core, heavy, opencode


@pytest.fixture
def parent_env(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    # Synthetic environment only: failed assertions must never display real parent credentials.
    env = {"HOME": str(home), "PATH": os.defpath, "LANG": "C.UTF-8",
           "HTTPS_PROXY": "http://proxy.invalid", "NO_PROXY": "localhost",
           "CODEX_HOME": str(home / ".codex"), "CLAUDE_CONFIG_DIR": str(home / ".claude"),
           "XDG_CONFIG_HOME": str(home / ".config"), "DBUS_SESSION_BUS_ADDRESS": "unix:path=/fixture",
           "AGENT_BRIDGE_HEAVY_DIR": str(tmp_path / "queue"),
           "AGENT_BRIDGE_HEAVY_MIN_AVAILABLE_MIB": "0", "AGENT_BRIDGE_HEAVY_MAX_LOAD": "1000000",
           "PYTHONPATH": str(Path(core.__file__).parents[1])}
    monkeypatch.setattr(os, "environ", env)
    return env


@pytest.mark.parametrize("name", ["API_KEY", "service_token", "ClientSecret", "PASSWORD",
                                  "DbCredential", "AUTH_HEADER", "SESSION_COOKIE", "SSH_AUTH_SOCK"])
def test_parent_secrets_are_removed_and_runtime_settings_survive(parent_env, name):
    parent_env[name] = "fixture"
    env = core.worker_env(Path("/jobs/owner/worker"))
    assert name not in env
    assert name in parent_env
    for retained in ("HOME", "PATH", "LANG", "HTTPS_PROXY", "NO_PROXY", "CODEX_HOME",
                     "CLAUDE_CONFIG_DIR", "XDG_CONFIG_HOME", "DBUS_SESSION_BUS_ADDRESS"):
        assert env[retained] == parent_env[retained]
    assert env[core.WORKER_FLAG] == "1"
    assert env["AGENT_BRIDGE_JOB"] == "owner/worker"


def test_pass_through_and_explicit_deny_are_exact_and_deny_wins(parent_env):
    parent_env.update(API_KEY="fixture", api_key="fixture", INTERNAL_ENDPOINT="fixture",
                      AGENT_BRIDGE_PASS_ENV=" API_KEY, INTERNAL_ENDPOINT ",
                      AGENT_BRIDGE_DENY_ENV="INTERNAL_ENDPOINT")
    env = core.worker_env()
    assert "API_KEY" in env and "api_key" not in env
    assert "INTERNAL_ENDPOINT" not in env
    parent_env["AGENT_BRIDGE_DENY_ENV"] = "API_KEY,INTERNAL_ENDPOINT"
    assert "API_KEY" not in core.worker_env()
    assert "OTHER_TOKEN" not in core.worker_env(OTHER_TOKEN="fixture")


def test_lab_registry_stays_on_host_when_worker_home_is_isolated(parent_env, tmp_path):
    expected = str(Path(parent_env["HOME"]) / ".local/state/agent-lab")
    env = core.worker_env(tmp_path / "owner/job", HOME=str(tmp_path / "isolated"))
    assert env["AGENT_LAB_HOME"] == expected
    parent_env["XDG_STATE_HOME"] = str(tmp_path / "state")
    assert core.worker_env()["AGENT_LAB_HOME"] == str(tmp_path / "state/agent-lab")
    parent_env["XDG_STATE_HOME"] = "relative"
    assert core.worker_env()["AGENT_LAB_HOME"] == expected
    parent_env["AGENT_LAB_HOME"] = str(tmp_path / "chosen")
    assert core.worker_env()["AGENT_LAB_HOME"] == str(tmp_path / "chosen")
    parent_env["AGENT_BRIDGE_DENY_ENV"] = "AGENT_LAB_HOME"
    assert "AGENT_LAB_HOME" not in core.worker_env()


@pytest.mark.parametrize("name", ["AGENT_BRIDGE_PASS_ENV", "AGENT_BRIDGE_DENY_ENV"])
@pytest.mark.parametrize("value", ["*", "API_KEY,,OTHER", "not a variable=fixture"])
def test_invalid_policy_does_not_echo_its_contents(parent_env, name, value, capsys):
    parent_env[name] = value
    with pytest.raises(ValueError) as error:
        core.worker_env()
    assert str(error.value) == f"{name} must contain comma-separated environment variable names"
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("backend", ["codex", "claude", "agy", "opencode"])
def test_backend_spawn_keeps_file_auth_without_parent_keys(parent_env, monkeypatch, tmp_path, backend):
    parent_env["UNRELATED_API_KEY"] = "fixture"
    home = Path(parent_env["HOME"])
    auths = [home / ".codex/auth.json", home / ".claude/.credentials.json",
             home / ".agy-accounts/a1" / agy.TOKEN, home / ".local/share/opencode/auth.json"]
    for auth in auths:
        auth.parent.mkdir(parents=True, exist_ok=True)
        auth.write_text("{}")
    monkeypatch.setattr(agy, "ACCOUNTS", home / ".agy-accounts")
    monkeypatch.setattr(core.shutil, "which", lambda name: "/usr/bin/" + name)
    job = tmp_path / "owner/job"
    job.mkdir(parents=True)
    state = {"cwd": str(tmp_path), "sandbox": "workspace-write", "writableRoots": [str(tmp_path)],
             "account": "a1", "title": "Environment probe", "model": opencode.ZDR_FREE[0]}
    path = job / "state.json"
    path.write_text(json.dumps(state))

    class Launched(Exception):
        pass

    def launch(command, **kwargs):
        env = kwargs["env"]
        assert "UNRELATED_API_KEY" not in env
        assert env["AGENT_LAB_HOME"] == str(home / ".local/state/agent-lab")
        assert env[core.WORKER_FLAG] == "1"
        if backend == "codex":
            auth = Path(env["CODEX_HOME"]) / "auth.json"
        elif backend == "claude":
            auth = Path(env["CLAUDE_CONFIG_DIR"]) / ".credentials.json"
        elif backend == "agy":
            auth = Path(env["HOME"]) / agy.TOKEN
        else:
            auth = Path(env["XDG_DATA_HOME"]) / "opencode/auth.json"
        assert auth.is_file()
        assert json.loads(auth.read_text()) == {}
        raise Launched

    monkeypatch.setattr(subprocess, "Popen", launch)
    with pytest.raises(Launched):
        if backend == "codex":
            codex.Rpc(str(tmp_path), job / "stderr.log")
        else:
            {"claude": claude, "agy": agy, "opencode": opencode}[backend].run(job, state, path, "probe")


def test_agy_account_queries_use_filtered_environment_and_existing_login(parent_env, monkeypatch):
    account = Path(parent_env["HOME"]) / ".agy-accounts/a1"
    auth = account / agy.TOKEN
    auth.parent.mkdir(parents=True)
    auth.write_text("{}")
    monkeypatch.setattr(agy, "ACCOUNTS", account.parent)
    parent_env["UNRELATED_API_KEY"] = "fixture"
    env = agy.account_env("a1")
    assert "UNRELATED_API_KEY" not in env
    assert (Path(env["HOME"]) / agy.TOKEN).is_file()


@pytest.mark.parametrize("passed", [False, True])
def test_heavy_exec_filters_actual_child_environment(parent_env, passed):
    parent_env["JOB_API_KEY"] = "fixture"
    if passed:
        parent_env["AGENT_BRIDGE_PASS_ENV"] = "JOB_API_KEY"
    code = "import json,os; print(json.dumps(sorted(os.environ)))"
    done = subprocess.run([sys.executable, "-m", "agent_bridge.cli", "heavy", "--",
                           sys.executable, "-c", code], env=parent_env,
                          text=True, capture_output=True, timeout=15)
    assert done.returncode == 0
    names = json.loads(done.stdout)
    assert ("JOB_API_KEY" in names) is passed
    assert "AGENT_BRIDGE_HEAVY_ACTIVE" in names


def test_scope_probes_and_exec_receive_the_filtered_environment(parent_env, monkeypatch):
    parent_env["UNRELATED_API_KEY"] = "fixture"
    monkeypatch.setattr(heavy.shutil, "which", lambda _: "/usr/bin/systemd-run")
    calls = []

    def probe(command, **kwargs):
        assert "UNRELATED_API_KEY" not in kwargs["env"]
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "--expand-environment=BOOL", "")

    monkeypatch.setattr(heavy.subprocess, "run", probe)
    monkeypatch.setattr(heavy, "pressure", lambda: SimpleNamespace(slice=None, groups=[]))

    class Executed(Exception):
        pass

    def execute(name, command, env):
        assert "UNRELATED_API_KEY" not in env
        assert env["PATH"] == parent_env["PATH"]
        raise Executed

    monkeypatch.setattr(heavy.os, "execvpe", execute)
    with pytest.raises(Executed):
        heavy.run(["unused"], "100")
    assert len(calls) == 2

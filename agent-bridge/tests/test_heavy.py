import os
import select
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from agent_bridge import cli, heavy, resources, watch
from agent_bridge.core import MESSAGING_RULE


@pytest.fixture
def host(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_BRIDGE_HEAVY_DIR", str(tmp_path / "queue"))
    monkeypatch.setenv("AGENT_BRIDGE_HEAVY_SLOTS", "1")
    monkeypatch.setenv("AGENT_BRIDGE_HEAVY_MIN_AVAILABLE_MIB", "0")
    monkeypatch.setenv("AGENT_BRIDGE_HEAVY_MAX_LOAD", "1000000")
    monkeypatch.delenv("AGENT_BRIDGE_HEAVY_ACTIVE", raising=False)
    proc = tmp_path / "proc"
    proc.mkdir()
    monkeypatch.setattr(resources, "PROC", proc)
    write_proc(proc)
    return proc


def write_proc(proc, available=4000000, load="0.1"):
    (proc / "meminfo").write_text(f"MemTotal: 8000000 kB\nMemAvailable: {available} kB\n")
    (proc / "loadavg").write_text(f"{load} 0.0 0.0 1/100 200\n")


def started(path):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.01)
    pytest.fail(f"process did not create {path.name}")


def launch(marker, release, **settings):
    code = ("import pathlib,sys,time; pathlib.Path(sys.argv[1]).touch(); "
            "\nwhile not pathlib.Path(sys.argv[2]).exists(): time.sleep(0.01)")
    env = {**os.environ, "PYTHONPATH": str(Path(heavy.__file__).parents[1]), **settings}
    return subprocess.Popen([sys.executable, "-m", "agent_bridge.cli", "heavy", "--",
                             sys.executable, "-c", code, str(marker), str(release)],
                            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


@pytest.mark.parametrize("crash", [False, True])
def test_process_slot_exclusion_and_release(host, tmp_path, crash):
    one, two, release = tmp_path / "one", tmp_path / "two", tmp_path / "release"
    first = launch(one, release)
    second = None
    try:
        started(one)
        second = launch(two, release)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            summary = heavy.status().summary
            if "heavy_queued=1" in summary:
                break
            time.sleep(0.01)
        else:
            pytest.fail("second process never queued")
        assert "heavy_running=1" in summary
        assert not two.exists()
        assert select.select([second.stderr], [], [], 10)[0]
        assert b"queue position 1/1" in second.stderr.readline()
        assert not two.exists()
        if crash:
            first.kill()
        else:
            release.touch()
        first.wait(timeout=5)
        assert first.returncode == (-signal.SIGKILL if crash else 0)
        started(two)
        release.touch()
        second.wait(timeout=5)
        assert second.returncode == 0
        assert "heavy_queued=0" in heavy.status().summary
        assert "heavy_running=0" in heavy.status().summary
    finally:
        for process in (first, second):
            if process is not None:
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=5)


def test_two_slots_and_conflicting_slot_configuration(host, tmp_path):
    release = tmp_path / "release"
    processes = [launch(tmp_path / str(n), release, AGENT_BRIDGE_HEAVY_SLOTS="2") for n in range(2)]
    try:
        for n in range(2):
            started(tmp_path / str(n))
        assert "heavy_running=2" in heavy.status().summary
        with pytest.raises(RuntimeError, match="slots differ"):
            heavy.run(["unused"])
    finally:
        release.touch()
        for process in processes:
            process.communicate(timeout=5)
            assert process.returncode == 0


class Executed(Exception):
    pass


@pytest.mark.parametrize("blocked", ["memory", "load"])
def test_headroom_wait_reads_proc_again(host, monkeypatch, capsys, blocked):
    monkeypatch.setenv("AGENT_BRIDGE_HEAVY_MIN_AVAILABLE_MIB", "1024")
    monkeypatch.setenv("AGENT_BRIDGE_HEAVY_MAX_LOAD", "2")
    write_proc(host, available=10 if blocked == "memory" else 4000000,
               load="3" if blocked == "load" else "0.1")
    sleeps = []

    def tick(seconds):
        sleeps.append(seconds)
        write_proc(host)

    def execute(name, args, env):
        assert args == ["program", "literal $ARG", "--flag"]
        assert env["AGENT_BRIDGE_HEAVY_ACTIVE"] == "1"
        raise Executed

    monkeypatch.setattr(heavy.time, "sleep", tick)
    monkeypatch.setattr(heavy.os, "execvpe", execute)
    with pytest.raises(Executed):
        heavy.run(["program", "literal $ARG", "--flag"])
    assert sleeps == [1]
    assert ("available memory" if blocked == "memory" else "load1") in capsys.readouterr().err
    assert not list(heavy.directory().glob("*.request"))


@pytest.mark.parametrize("code", [0, 37])
def test_cli_exit_code_and_stdio_passthrough(host, code):
    code_text = "import sys; print(sys.stdin.read()); sys.exit(int(sys.argv[1]))"
    done = subprocess.run([sys.executable, "-m", "agent_bridge.cli", "heavy", "--",
                           sys.executable, "-c", code_text,
                           str(code)], input="from stdin", capture_output=True, text=True, timeout=10)
    assert done.returncode == code
    assert done.stdout == "from stdin\n"
    assert "heavy: admitted" in done.stderr


@pytest.mark.parametrize("failure", ["missing", "bus", "timeout"])
def test_systemd_unavailable_falls_back_before_command(host, monkeypatch, capsys, failure):
    calls = []
    monkeypatch.setattr(heavy.shutil, "which", lambda _: None if failure == "missing" else "/bin/systemd-run")

    def probe(args, **kwargs):
        calls.append(args)
        if args[-1] == "--help":
            return subprocess.CompletedProcess(args, 0, "--expand-environment=BOOL", "")
        if failure == "timeout":
            raise subprocess.TimeoutExpired(args, 5)
        assert args[-1] == "/usr/bin/true"
        return subprocess.CompletedProcess(args, 1)

    executed = []

    def execute(name, args, env):
        executed.append(args)
        raise Executed

    monkeypatch.setattr(heavy.subprocess, "run", probe)
    monkeypatch.setattr(heavy.os, "execvpe", execute)
    with pytest.raises(Executed):
        heavy.run(["actual-command"], "100")
    assert executed == [["actual-command"]]
    assert "WITHOUT requested memory cap" in capsys.readouterr().err
    assert len(calls) == (0 if failure == "missing" else 2)


@pytest.mark.parametrize("modern", [False, True])
def test_systemd_scope_reenters_before_locking_and_never_retries(host, monkeypatch, modern):
    monkeypatch.setattr(heavy.shutil, "which", lambda _: "/bin/systemd-run")

    def probe(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, "--expand-environment=BOOL" if modern else "", "")

    def execute(name, args):
        assert name == "systemd-run"
        assert ("--expand-environment=no" in args) is modern
        assert "MemoryMax=104857600" in args
        assert args[-3:] == ["--", "program", "$literal"]
        assert "--memory-max-mib" not in args
        assert not heavy.directory().exists()
        raise Executed

    monkeypatch.setattr(heavy.subprocess, "run", probe)
    monkeypatch.setattr(heavy.os, "execvp", execute)
    with pytest.raises(Executed):
        heavy.run(["program", "$literal"], "100")


@pytest.mark.parametrize("value", ["nan", "inf", "-1"])
def test_invalid_pressure_is_rejected(host, value):
    write_proc(host, load=value)
    with pytest.raises(ValueError, match="invalid host"):
        heavy.pressure()


def test_defaults_private_directory_and_nested_rejection(host, monkeypatch, tmp_path):
    for key in ("SLOTS", "MIN_AVAILABLE_MIB", "MAX_LOAD"):
        monkeypatch.delenv("AGENT_BRIDGE_HEAVY_" + key)
    monkeypatch.setattr(resources.os, "cpu_count", lambda: 12)
    policy = heavy.limits(heavy.pressure())
    assert policy.slots == 1 and policy.load == pytest.approx(9.6)
    assert policy.available == 1563 * heavy.MIB
    insecure = tmp_path / "insecure"
    insecure.mkdir(mode=0o755)
    monkeypatch.setenv("AGENT_BRIDGE_HEAVY_DIR", str(insecure))
    with pytest.raises(RuntimeError, match="private directory"):
        heavy.prepare()
    monkeypatch.setenv("AGENT_BRIDGE_HEAVY_ACTIVE", "1")
    with pytest.raises(RuntimeError, match="nested"):
        heavy.run(["anything"])
    assert "agent-bridge heavy -- <command>" in MESSAGING_RULE


def test_owners_and_watch_report_pressure_once(host, monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("AGENT_BRIDGE_HEAVY_MIN_AVAILABLE_MIB", "1024")
    write_proc(host, available=10)
    monkeypatch.setattr(cli, "JOBS", tmp_path / "absent")
    monkeypatch.setattr(sys, "argv", ["agent-bridge", "owners"])
    cli.main()
    output = capsys.readouterr()
    assert "available=" in output.out and "heavy_queued=0" in output.out
    assert "WARNING: host overloaded" in output.err
    monkeypatch.setattr(watch, "JOBS", tmp_path / "absent")
    clock = iter([0, 11, 22, 33, 44])
    monkeypatch.setattr(watch.time, "time", lambda: next(clock))
    monkeypatch.setattr(watch.time, "sleep", lambda _: None)
    watch.watch(["absent"])
    output = capsys.readouterr().out
    assert "host: available=" in output and output.count("WARNING: host overloaded") == 1

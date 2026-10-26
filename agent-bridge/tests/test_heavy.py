import fcntl
import json
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
    # In-process exec mocks must not move pytest itself into another process group.
    monkeypatch.setattr(heavy.os, "setpgid", lambda *_: None)
    proc = tmp_path / "proc"
    proc.mkdir()
    monkeypatch.setattr(resources, "PROC", proc)
    write_proc(proc)
    return proc


def write_proc(proc, available=4000000, load="0.1", total=8000000):
    (proc / "meminfo").write_text(f"MemTotal: {total} kB\nMemAvailable: {available} kB\n")
    (proc / "loadavg").write_text(f"{load} 0.0 0.0 1/100 200\n")


def started(path):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.01)
    pytest.fail(f"process did not create {path.name}")


def launch(marker, release, mem=None, exclusive=False, command=None, **settings):
    code = ("import pathlib,sys,time; pathlib.Path(sys.argv[1]).touch(); "
            "\nwhile not pathlib.Path(sys.argv[2]).exists(): time.sleep(0.01)")
    env = {**os.environ, "PYTHONPATH": str(Path(heavy.__file__).parents[1]), **settings}
    entry = ("import sys; from pathlib import Path; from agent_bridge import cli,resources; "
             "resources.PROC=Path(sys.argv.pop(1)); cli.main()")
    flags = (["--mem", mem] if mem else []) + (["--exclusive"] if exclusive else [])
    return subprocess.Popen([sys.executable, "-c", entry, str(resources.PROC), "heavy", *flags, "--",
                             *(command or [sys.executable, "-c", code, str(marker), str(release)])],
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
        waiting = second.stderr.readline()
        assert b"queue position 1/1" in waiting
        assert b"holder=" in waiting and b"elapsed=" in waiting and b"alive=yes (kernel lock)" in waiting
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


def test_free_slot_waiting_on_an_earlier_request_says_so(host, tmp_path):
    folder = heavy.prepare()
    earlier = heavy.locked_file(folder / f"{0:020d}-earlier.request")
    fcntl.flock(earlier, fcntl.LOCK_EX)  # alive but not yet admitted: it claims on its next poll
    heavy.write_request(earlier, {"running": False, "slots": 1})
    later = launch(tmp_path / "later", tmp_path / "release")
    try:
        assert select.select([later.stderr], [], [], 10)[0]
        waiting = later.stderr.readline()
        assert b"queue position 2/2; 0/1 slots busy" in waiting
        assert b"free slot is going to the earlier request (standalone)" in waiting
        assert not (tmp_path / "later").exists()
    finally:
        later.kill()
        later.communicate(timeout=5)
        os.close(earlier)


def test_configured_hard_cap_allows_two_jobs(host, tmp_path):
    release = tmp_path / "release"
    processes = [launch(tmp_path / str(n), release, AGENT_BRIDGE_HEAVY_SLOTS="2") for n in range(2)]
    try:
        for n in range(2):
            started(tmp_path / str(n))
        assert "heavy_running=2" in heavy.status().summary
        third = launch(tmp_path / "third", release, AGENT_BRIDGE_HEAVY_SLOTS="2")
        processes.append(third)
        assert select.select([third.stderr], [], [], 10)[0]
        assert b"hard job cap reached" in third.stderr.readline()
        assert not (tmp_path / "third").exists()
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
        active = env.get("AGENT_BRIDGE_HEAVY_ACTIVE")
        env.clear()
        assert args == ["program", "literal $ARG", "--flag"]
        assert active == "1"
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
        env.clear()
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

    def execute(name, args, env):
        env.clear()
        assert name == "systemd-run"
        assert ("--expand-environment=no" in args) is modern
        assert "MemoryMax=104857600" in args
        assert args[-3:] == ["--", "program", "$literal"]
        assert "--memory-max-mib" not in args
        assert not heavy.directory().exists()
        raise Executed

    monkeypatch.setattr(heavy.subprocess, "run", probe)
    monkeypatch.setattr(heavy.os, "execvpe", execute)
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
    assert policy.slots is None and policy.load == pytest.approx(9.6)
    assert policy.available == 1563 * heavy.MIB
    insecure = tmp_path / "insecure"
    insecure.mkdir(mode=0o755)
    monkeypatch.setenv("AGENT_BRIDGE_HEAVY_DIR", str(insecure))
    with pytest.raises(RuntimeError, match="private directory"):
        heavy.prepare()
    monkeypatch.setenv("AGENT_BRIDGE_HEAVY_ACTIVE", "1")
    with pytest.raises(RuntimeError, match="nested"):
        heavy.run(["anything"])
    assert "agent-bridge heavy --mem SIZE -- <command>" in MESSAGING_RULE


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


def test_holder_record_contains_identity_but_no_arguments(host, monkeypatch):
    monkeypatch.setenv("AGENT_BRIDGE_JOB", "owner/benchmark")
    namespace = os.readlink("/proc/self/ns/pid")
    monkeypatch.setenv("AGENT_BRIDGE_HOST_PID_NAMESPACE", namespace)
    captured = []

    def execute(name, command, env):
        env.clear()
        records = list(heavy.directory().glob("*.request"))
        assert heavy.reservation_path(records[0]).stat().st_mode & 0o777 == 0o600
        captured.append(json.loads(records[0].read_text()))
        metadata = heavy.reservation(records[0], captured[-1])
        assert metadata["need"] == 1024 * heavy.MIB and metadata["exclusive"] is False
        raise Executed

    monkeypatch.setattr(heavy.os, "execvpe", execute)
    with pytest.raises(Executed):
        heavy.run(["/usr/bin/benchmark", "fixture-private-argument"])
    row = captured[0]
    assert row["job"] == "owner/benchmark" and row["command"] == "benchmark"
    assert row["running"] and row["pid"] == os.getpid() and row["host_pid"] == os.getpid()
    assert row["started_at"] and row["started_ns"] > 0
    assert "fixture-private-argument" not in json.dumps(row)
    assert not list(heavy.directory().glob("*.request"))


def test_dead_holder_is_removed_by_kernel_lock_state_without_pid_access(host):
    folder = heavy.prepare()
    record = folder / "000.request"
    record.write_text(json.dumps({"running": True, "slots": 1, "job": "owner/dead"}))
    dead = []
    with heavy.gate(folder):
        assert heavy.entries(folder, dead=dead) == []
    assert dead == ["owner/dead"] and not record.exists()


def test_host_observer_resolves_a_namespaced_holder_pid(monkeypatch, tmp_path):
    proc = tmp_path / "proc"
    (proc / "self/ns").mkdir(parents=True)
    (proc / "self/ns/pid").symlink_to("pid:[host]")
    (proc / "42/ns").mkdir(parents=True)
    (proc / "42/ns/pid").symlink_to("pid:[worker]")
    (proc / "42/status").write_text("NSpid:\t42\t3\n")
    monkeypatch.setattr(heavy, "PROC", proc)
    row = {"host_namespace": "pid:[host]", "namespace": "pid:[worker]", "pid": 3}
    assert heavy.resolve_host_pid(row) == 42
    row["host_namespace"] = "pid:[other]"
    assert heavy.resolve_host_pid(row) is None


def test_light_command_runs_directly_while_heavy_slot_is_occupied(host, tmp_path):
    marker, release = tmp_path / "holder", tmp_path / "release"
    holder = launch(marker, release)
    try:
        started(marker)
        done = subprocess.run([sys.executable, "-c", "print('light completed')"],
                              capture_output=True, text=True, timeout=5)
        assert done.returncode == 0 and done.stdout == "light completed\n"
        assert holder.poll() is None
    finally:
        release.touch()
        holder.communicate(timeout=5)


def finish(processes, releases):
    for release in releases:
        release.touch()
    for process in processes:
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=5)


def test_memory_fit_runs_two_jobs_without_a_slot_cap(host, monkeypatch, tmp_path):
    monkeypatch.delenv("AGENT_BRIDGE_HEAVY_SLOTS")
    release = tmp_path / "release"
    processes = [launch(tmp_path / str(n), release, mem="1G", AGENT_BRIDGE_JOB=f"owner/job{n}")
                 for n in range(2)]
    try:
        for n in range(2):
            started(tmp_path / str(n))
        report = heavy.status().summary
        assert "heavy_running=2" in report and "heavy_reserved=2048MiB" in report
        assert "heavy=owner/job0 need=1024MiB" in report
        assert "heavy=owner/job1 need=1024MiB" in report
    finally:
        finish(processes, [release])


@pytest.mark.parametrize("crash", [False, True])
def test_memory_that_does_not_fit_waits_and_exit_releases_need(host, monkeypatch, tmp_path, crash):
    monkeypatch.delenv("AGENT_BRIDGE_HEAVY_SLOTS")
    write_proc(host, total=4000000)  # fake holders use no memory: capacity must bound 2G + 3G
    first_release, second_release = tmp_path / "release1", tmp_path / "release2"
    first = launch(tmp_path / "first", first_release, mem="2G")
    processes = [first]
    try:
        started(tmp_path / "first")
        second = launch(tmp_path / "second", second_release, mem="3G")
        processes.append(second)
        assert select.select([second.stderr], [], [], 10)[0]
        waiting = second.stderr.readline()
        assert b"declared memory needs do not fit" in waiting
        assert b"need=2048MiB" in waiting and b"reserved=2048MiB" in waiting
        assert not (tmp_path / "second").exists()
        if crash:
            first.kill()
        else:
            first_release.touch()
        first.wait(timeout=5)
        started(tmp_path / "second")
        report = heavy.status().summary
        assert "heavy_running=1" in report and "heavy_reserved=3072MiB" in report
    finally:
        finish(processes, [first_release, second_release])


@pytest.mark.parametrize("first_exclusive", [False, True])
def test_exclusive_excludes_other_jobs_in_both_directions(host, monkeypatch, tmp_path, first_exclusive):
    monkeypatch.delenv("AGENT_BRIDGE_HEAVY_SLOTS")
    first_release, second_release = tmp_path / "release1", tmp_path / "release2"
    first = launch(tmp_path / "first", first_release, mem="1G", exclusive=first_exclusive)
    processes = [first]
    try:
        started(tmp_path / "first")
        second = launch(tmp_path / "second", second_release, mem="1G", exclusive=not first_exclusive)
        processes.append(second)
        assert select.select([second.stderr], [], [], 10)[0]
        assert b"exclusive" in second.stderr.readline()
        assert not (tmp_path / "second").exists()
        first_release.touch()
        first.wait(timeout=5)
        started(tmp_path / "second")
    finally:
        finish(processes, [first_release, second_release])


def test_reservation_is_removed_with_a_dead_request(host):
    folder = heavy.prepare()
    record = folder / "000.request"
    record.write_text('{"running":true,"slots":1}')
    metadata = heavy.reservation_path(record)
    metadata.write_text('{"need":1048576,"exclusive":false,"queued_ns":0,"cap":null}')
    with heavy.gate(folder):
        assert heavy.entries(folder) == []
    assert not record.exists() and not metadata.exists()


@pytest.mark.parametrize("mem", ["0", "-1G", "nan", "1GB", "0.1", "100G"])
def test_invalid_or_impossible_memory_need_fails_before_queueing(host, mem):
    with pytest.raises(ValueError):
        heavy.run(["unused"], mem=mem)
    assert not heavy.directory().exists()


@pytest.mark.parametrize("aged", [False, True])
def test_process_backfill_and_starvation_bound(host, monkeypatch, tmp_path, aged):
    monkeypatch.delenv("AGENT_BRIDGE_HEAVY_SLOTS")
    write_proc(host, total=4000000)  # fake holders use no memory: capacity must bound 2G + 3G
    holder_release, head_release, small_release = [tmp_path / name for name in ("free1", "free2", "free3")]
    holder = launch(tmp_path / "holder", holder_release, mem="2G")
    processes = [holder]
    try:
        started(tmp_path / "holder")
        head = launch(tmp_path / "head", head_release, mem="3G", AGENT_BRIDGE_JOB="owner/head")
        processes.append(head)
        assert select.select([head.stderr], [], [], 10)[0]
        assert b"do not fit" in head.stderr.readline()
        if aged:
            folder = heavy.directory()
            with heavy.gate(folder):
                path, row = next((path, row) for path, row in heavy.entries(folder)
                                 if row.get("job") == "owner/head")
                metadata = heavy.reservation(path, row)
                metadata["queued_ns"] = time.monotonic_ns() - 301 * 1000000000
                heavy.reservation_path(path).write_text(json.dumps(metadata))
        small = launch(tmp_path / "small", small_release, mem="1G")
        processes.append(small)
        if aged:
            assert select.select([small.stderr], [], [], 10)[0]
            assert b"backfill paused" in small.stderr.readline()
            assert not (tmp_path / "small").exists()
        else:
            started(tmp_path / "small")
            assert not (tmp_path / "head").exists()
            small_release.touch()
            small.wait(timeout=5)
        holder_release.touch()
        holder.wait(timeout=5)
        started(tmp_path / "head")
        if aged:
            assert not (tmp_path / "small").exists()
            head_release.touch()
            head.wait(timeout=5)
            started(tmp_path / "small")
    finally:
        finish(processes, [holder_release, head_release, small_release])


def test_scope_reentry_preserves_declared_need_and_exclusivity(host, monkeypatch):
    monkeypatch.setattr(heavy, "scope_prefix", lambda _: ["systemd-run"])

    def execute(name, command, env):
        env.clear()
        assert command[command.index("--mem") + 1] == str(2500 * heavy.MIB)
        assert "--exclusive" in command
        assert command[-3:] == ["--", "program", "literal"]
        raise Executed

    monkeypatch.setattr(heavy.os, "execvpe", execute)
    with pytest.raises(Executed):
        heavy.run(["program", "literal"], "4096", mem="2500M", exclusive=True)

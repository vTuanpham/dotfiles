import fcntl
import json
import os
import select
import signal
import sys
import time
from contextlib import nullcontext

import pytest
import test_heavy
from agent_resources import cli, heavy
from agent_resources import control as heavy_control
from test_heavy import finish, launch, started

from agent_bridge import core, owner_binding, status, status_render

host = test_heavy.host


@pytest.fixture(autouse=True)
def root(monkeypatch):
    monkeypatch.delenv("AGENT_RESOURCES_WORKER", raising=False)
    monkeypatch.delenv("AGENT_RESOURCES_HOST_PID_NAMESPACE", raising=False)


def command(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["agent-resources", *args])
    code = cli.main()
    if code:
        raise SystemExit(code)


def rows():
    folder = heavy.prepare()
    with heavy.gate(folder):
        return heavy.entries(folder)


def wait_queued(process):
    assert select.select([process.stderr], [], [], 10)[0]
    return process.stderr.readline()


def test_list_and_cancel_queued_without_stopping_worker_or_holder(host, tmp_path, monkeypatch, capsys):
    release = tmp_path / "release"
    holder = launch(tmp_path / "holder", release, AGENT_RESOURCES_JOB="owner/holder")
    processes = [holder]
    try:
        started(tmp_path / "holder")
        queued = launch(tmp_path / "queued", release, AGENT_RESOURCES_JOB="owner/queued")
        processes.append(queued)
        wait_queued(queued)
        command(monkeypatch, "list")
        output = capsys.readouterr().out
        assert "owner/holder" in output and "owner/queued" in output
        assert "1024MiB no running elapsed=" in output
        assert "1024MiB no queued wait=" in output
        assert "yes(kernel-lock)" in output
        path, _ = next((p, r) for p, r in rows() if r["job"] == "owner/queued")
        identifier = heavy_control.request_id(path)
        assert identifier in output
        command(monkeypatch, "cancel", identifier)
        _, stderr = queued.communicate(timeout=5)
        assert queued.returncode == 125
        assert b"cancelled by root while queued; exit=125" in stderr
        assert not (tmp_path / "queued").exists()
        assert holder.poll() is None and not path.exists()
        assert not heavy.control_path(path).exists()
        assert "heavy_queued=0" in status_render.pressure(*status.collect_host()[:2])
    finally:
        finish(processes, [release])


def test_cancel_running_by_job_releases_need_and_admits_waiter(host, tmp_path, monkeypatch, capsys):
    release = tmp_path / "release"
    holder = launch(tmp_path / "holder", release, AGENT_RESOURCES_JOB="owner/holder")
    processes = [holder]
    try:
        started(tmp_path / "holder")
        queued = launch(tmp_path / "queued", release)
        processes.append(queued)
        wait_queued(queued)
        command(monkeypatch, "cancel", "owner/holder")
        holder.communicate(timeout=5)
        assert holder.returncode == -signal.SIGTERM
        assert "SIGTERM" in capsys.readouterr().err
        started(tmp_path / "queued")
        assert "heavy_running=1" in status_render.pressure(*status.collect_host()[:2])
        assert all(row["job"] != "owner/holder" for _, row in rows())
    finally:
        finish(processes, [release])


@pytest.mark.parametrize("parent_ignores", [False, True])
def test_cancel_escalates_for_child_even_after_parent_exits(host, tmp_path, monkeypatch, parent_ignores):
    monkeypatch.setattr(heavy_control, "TERM_GRACE", 0.1)
    marker, child_pid = tmp_path / "holder", tmp_path / "child-pid"
    ready = tmp_path / "child-ready"
    child = ("import pathlib,signal,sys,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); "
             f"pathlib.Path({str(ready)!r}).touch(); time.sleep(60)")
    code = ("import pathlib,signal,subprocess,sys,time; "
            + ("signal.signal(signal.SIGTERM,signal.SIG_IGN); " if parent_ignores else "") +
            "p=subprocess.Popen([sys.executable,'-c',sys.argv[1]]); "
            "pathlib.Path(sys.argv[2]).write_text(str(p.pid)); "
            f"\nwhile not pathlib.Path({str(ready)!r}).exists(): time.sleep(.01)"
            "\npathlib.Path(sys.argv[3]).touch(); time.sleep(60)")
    process = launch(marker, tmp_path / "unused", AGENT_RESOURCES_JOB="owner/stubborn",
                     command=[sys.executable, "-c", code, child, str(child_pid), str(marker)])
    try:
        started(marker)
        pid = int(child_pid.read_text())
        command(monkeypatch, "cancel", "owner/stubborn")
        process.communicate(timeout=5)
        assert process.returncode == (-signal.SIGKILL if parent_ignores else -signal.SIGTERM)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            state = heavy.PROC / str(pid) / "stat"
            try:
                process_state = state.read_text().rpartition(")")[2].split()[0]
            except (FileNotFoundError, ProcessLookupError):
                break
            if process_state == "Z":
                break
            time.sleep(.01)
        else:
            pytest.fail("heavy command child survived cancellation")
        assert "heavy_running=0" in status_render.pressure(*status.collect_host()[:2])
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
        process.communicate(timeout=5)


def test_pause_resume_gates_only_new_admissions(host, tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("AGENT_RESOURCES_SLOTS")
    release = tmp_path / "release"
    holder = launch(tmp_path / "holder", release, AGENT_RESOURCES_JOB="owner/holder")
    processes = [holder]
    try:
        started(tmp_path / "holder")
        command(monkeypatch, "pause", "--reason", "benchmark review")
        report = status_render.pressure(*status.collect_host()[:2])
        assert "heavy_paused=yes (paused by root: benchmark review)" in report
        queued = launch(tmp_path / "queued", release)
        processes.append(queued)
        assert b"paused by root: benchmark review" in wait_queued(queued)
        assert not (tmp_path / "queued").exists() and holder.poll() is None
        command(monkeypatch, "list")
        assert "paused by root: benchmark review" in capsys.readouterr().out
        command(monkeypatch, "resume")
        started(tmp_path / "queued")
        assert holder.poll() is None
        assert "heavy_paused" not in status_render.pressure(*status.collect_host()[:2])
    finally:
        finish(processes, [release])


def test_pause_clock_excludes_multiple_pauses_for_old_and_new_waiters(host, monkeypatch):
    clock = [100 * 10**9]
    monkeypatch.setattr(heavy.time, "monotonic_ns", lambda: clock[0])
    queued = {"queued_ns": 90 * 10**9, "control": {"pause_ns": 0}}
    heavy_control.pause("review")
    clock[0] += 2000 * 10**9
    paused = heavy.pause_state(heavy.directory())
    assert heavy.waited_ns(queued, paused, clock[0]) == 10 * 10**9
    during = {"queued_ns": clock[0], "control": {"pause_ns": heavy.pause_clock(paused, clock[0])}}
    clock[0] += 100 * 10**9
    heavy_control.pause("new reason")  # changing reason must not reset the clock
    heavy_control.resume()
    clock[0] += 50 * 10**9
    resumed = heavy.pause_state(heavy.directory())
    assert heavy.waited_ns(queued, resumed, clock[0]) == 60 * 10**9
    assert heavy.waited_ns(during, resumed, clock[0]) == 50 * 10**9


def test_ambiguous_missing_and_invalid_requests_are_refused(host, tmp_path):
    heavy_control.pause("hold")
    release = tmp_path / "release"
    processes = [launch(tmp_path / str(n), release, AGENT_RESOURCES_JOB="owner/same") for n in range(2)]
    try:
        for process in processes:
            wait_queued(process)
        with pytest.raises(ValueError, match="ambiguous"):
            heavy_control.cancel("owner/same")
        with pytest.raises(ValueError, match="no live"):
            heavy_control.cancel("absent")
        assert all(process.poll() is None for process in processes)
        legacy = heavy.directory() / "000-legacy.request"
        fd = heavy.locked_file(legacy)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            heavy.write_request(fd, {"running": False, "slots": 1})
            with pytest.raises(ValueError, match="invalid heavy queue entry"):
                heavy_control.pause("replacement reason")
            assert heavy.pause_state(heavy.directory())["reason"] == "hold"
            with pytest.raises(ValueError, match="invalid heavy queue entry"):
                heavy_control.cancel("legacy")
        finally:
            os.close(fd)
    finally:
        heavy_control.resume()
        finish(processes, [release])


@pytest.mark.parametrize("queued", [False, True])
def test_crash_cleans_request_controls_but_preserves_explicit_pause(host, tmp_path, capsys, queued):
    if queued:
        heavy_control.pause("operator maintenance")
    process = launch(tmp_path / "never", tmp_path / "release")
    try:
        if queued:
            wait_queued(process)
        else:
            started(tmp_path / "never")
            heavy_control.pause("operator maintenance")
        assert any(heavy.directory().glob("*.request.control"))
        process.kill()
        process.communicate(timeout=5)
        (heavy.directory() / ".state-interrupted").write_text("partial")
        (heavy.directory() / "orphan.request.control").write_text("partial")
        heavy_control.listing()
        assert "operator maintenance" in capsys.readouterr().out
        assert not list(heavy.directory().glob("*.request*"))
        assert not list(heavy.directory().glob(".state-*"))
        heavy_control.resume()
        assert heavy.pause_state(heavy.directory())["reason"] is None
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)


@pytest.mark.parametrize("args", [("list",), ("cancel", "anything"),
                                 ("pause", "--reason", "test"), ("resume",)])
def test_workers_cannot_control_queue_but_can_run_heavy(host, monkeypatch, args, capsys):
    monkeypatch.setenv("AGENT_RESOURCES_WORKER", "1")
    with pytest.raises(SystemExit) as error:
        command(monkeypatch, *args)
    assert error.value.code == 1
    assert "delegated workers cannot control the heavy queue" in capsys.readouterr().err
    assert not heavy.directory().exists()


def test_worker_can_still_run_heavy_commands(host, monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_RESOURCES_WORKER", "1")
    marker, release = tmp_path / "allowed", tmp_path / "release"
    process = launch(marker, release)
    try:
        started(marker)
    finally:
        finish([process], [release])
    assert process.returncode == 0


@pytest.mark.parametrize("data", [[], {"group": True},
                                 {"group": True, "cancelled": 1, "pause_ns": 0}])
def test_control_state_is_strict(host, data):
    folder = heavy.prepare()
    path = folder / "sample.request"
    heavy.control_path(path).write_text(json.dumps(data))
    with pytest.raises(ValueError, match="invalid heavy request control"):
        heavy.control(path)


@pytest.mark.parametrize("reason", ["", "line\nbreak", "x" * 201])
def test_pause_reason_validation_does_not_echo_input(host, reason):
    with pytest.raises(ValueError, match="pause reason must be"):
        heavy_control.pause(reason)
    assert not heavy.directory().exists()


def test_pid_identity_mismatch_never_signals(host, tmp_path, monkeypatch):
    release = tmp_path / "release"
    process = launch(tmp_path / "holder", release, AGENT_RESOURCES_JOB="owner/holder")
    try:
        started(tmp_path / "holder")
        monkeypatch.setattr(heavy_control, "process_has_request", lambda *_: False)
        with pytest.raises(RuntimeError, match="identity changed"):
            heavy_control.cancel("owner/holder")
        assert process.poll() is None
    finally:
        finish([process], [release])


def test_stale_root_cannot_cancel_an_owners_heavy_request(host, tmp_path, monkeypatch):
    owner = core.JOBS / "owner"
    owner.mkdir(parents=True)
    owner_binding.record(owner, {"backend": "codex", "session_id": "current-root"})
    request = tmp_path / "sample-123.request"
    control = {"group": None, "cancelled": False, "pause_ns": 0}
    row = {"job": "owner/job", "owner": "codex:current-root", "running": False,
           "control": control, "pid": None}
    monkeypatch.setattr(heavy, "prepare", lambda: tmp_path)
    monkeypatch.setattr(heavy, "gate", lambda _: nullcontext())
    monkeypatch.setattr(heavy, "entries", lambda _: [(request, row)])
    monkeypatch.setattr(heavy, "control_path", lambda path: tmp_path / "request.control")
    monkeypatch.setattr(heavy, "write_state", lambda *_: pytest.fail("stale root changed request"))
    monkeypatch.setenv("CODEX_THREAD_ID", "stale-root")

    with pytest.raises(RuntimeError, match="different root session"):
        heavy_control.cancel("123")
    assert not control["cancelled"]


def test_atomic_pause_update_survives_interrupted_write(host, monkeypatch):
    heavy_control.pause("original reason")

    def interrupted(*_):
        raise OSError("interrupted fixture write")

    monkeypatch.setattr(heavy.os, "replace", interrupted)
    with pytest.raises(OSError, match="interrupted fixture"):
        heavy_control.pause("replacement reason")
    assert heavy.pause_state(heavy.directory())["reason"] == "original reason"
    assert not list(heavy.directory().glob(".state-*"))


@pytest.mark.parametrize("data", [None, [], {"reason": "invalid"},
                                 {"reason": "test", "since_ns": True, "total_ns": 0},
                                 {"reason": "line\nbreak", "since_ns": 0, "total_ns": 0}])
def test_pause_state_fails_closed_on_invalid_data(host, data):
    folder = heavy.prepare()
    (folder / "pause.json").write_text(json.dumps(data))
    with pytest.raises(ValueError, match="invalid heavy"):
        heavy.pause_state(folder)

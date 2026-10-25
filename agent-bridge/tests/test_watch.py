import itertools
import json
import os

from agent_bridge import watch as watcher


def test_timeout_gives_up_while_a_runner_is_alive(monkeypatch, tmp_path, capsys):
    root, _ = setup_job(tmp_path)
    monkeypatch.setattr(watcher, "JOBS", root)
    monkeypatch.setattr(watcher, "running", lambda state: True)
    clock = iter(range(0, 1000, 10))
    monkeypatch.setattr(watcher.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(watcher.time, "sleep", lambda _: None)
    assert watcher.watch(["owner"], until_event=True, timeout=30) is False
    assert "30s passed with jobs still running" in capsys.readouterr().out


def setup_job(tmp_path):
    root = tmp_path / "jobs"
    job = root / "owner" / "worker"
    job.mkdir(parents=True)
    (job / "state.json").write_text(json.dumps({"runnerPid": 4321}))
    (job / "live.jsonl").write_text('{"kind":"message","level":"info"}\n')
    return root, job


def test_until_event_exits_after_urgent(monkeypatch, tmp_path, capsys):
    root, job = setup_job(tmp_path)
    state_path = job / "state.json"
    state = json.loads(state_path.read_text())
    state["title"] = "Fix startup"
    state_path.write_text(json.dumps(state))
    monkeypatch.setattr(watcher, "JOBS", root)
    monkeypatch.setattr(watcher, "running", lambda state: state.get("runnerPid") == 4321)
    sleeps = 0

    def tick(_):
        nonlocal sleeps
        sleeps += 1
        if sleeps == 1:
            with (job / "live.jsonl").open("a") as stream:
                stream.write('{"kind":"error","level":"urgent","message":"failed"}\n')

    monkeypatch.setattr(watcher.time, "sleep", tick)
    watcher.watch(["owner"], until_event=True)
    output = capsys.readouterr().out
    assert "status: worker (Fix startup) running" in output
    assert "worker (Fix startup): error | failed" in output
    assert sleeps == 1


def test_resumed_job_gets_a_fresh_stall_clock(monkeypatch, tmp_path, capsys):
    root, job = setup_job(tmp_path)
    os.utime(job / "live.jsonl", (0, 0))
    monkeypatch.setattr(watcher, "JOBS", root)
    alive = iter([True, True, False])
    monkeypatch.setattr(watcher, "running", lambda state: next(alive, False))
    times = iter([1000, 1001, 1002])
    monkeypatch.setattr(watcher.time, "time", lambda: next(times, 1002))
    monkeypatch.setattr(watcher.time, "sleep", lambda _: None)
    watcher.watch(["owner"], until_event=True, stall_min=1)
    output = capsys.readouterr().out
    assert "status: worker running" in output
    assert "stalled?" not in output


def test_new_stall_wakes_an_until_event_watch(monkeypatch, tmp_path, capsys):
    root, job = setup_job(tmp_path)
    os.utime(job / "live.jsonl", (0, 0))
    monkeypatch.setattr(watcher, "JOBS", root)
    monkeypatch.setattr(watcher, "running", lambda state: True)
    times = iter([1000, 1200])
    monkeypatch.setattr(watcher.time, "time", lambda: next(times, 1200))
    monkeypatch.setattr(watcher.time, "sleep", lambda _: None)
    assert watcher.watch(["owner"], until_event=True, stall_min=1, timeout=10_000) is True
    assert "silent for 3m while running (stalled?)" in capsys.readouterr().out


def test_a_silent_job_still_using_cpu_is_not_stalled(monkeypatch, tmp_path, capsys):
    root, job = setup_job(tmp_path)
    os.utime(job / "live.jsonl", (0, 0))
    monkeypatch.setattr(watcher, "JOBS", root)
    monkeypatch.setattr(watcher, "running", lambda state: True)
    clock, cpu = itertools.count(1000, 100), itertools.count(0, 50)
    monkeypatch.setattr(watcher.time, "time", lambda: next(clock))
    monkeypatch.setattr(watcher.time, "sleep", lambda _: None)
    monkeypatch.setattr(watcher, "tree_cpu", lambda pid: (next(cpu), {1}))
    monkeypatch.setattr(watcher, "socket_bytes", lambda pids: {})
    assert watcher.watch(["owner"], until_event=True, stall_min=1, timeout=0.2) is False
    assert "stalled?" not in capsys.readouterr().out


def test_a_silent_job_streaming_over_the_network_is_not_stalled(monkeypatch, tmp_path, capsys):
    root, job = setup_job(tmp_path)
    os.utime(job / "live.jsonl", (0, 0))
    monkeypatch.setattr(watcher, "JOBS", root)
    monkeypatch.setattr(watcher, "running", lambda state: True)
    clock, received = itertools.count(1000, 100), itertools.count(0, 1 << 20)
    monkeypatch.setattr(watcher.time, "time", lambda: next(clock))
    monkeypatch.setattr(watcher.time, "sleep", lambda _: None)
    monkeypatch.setattr(watcher, "tree_cpu", lambda pid: (7.0, {1}))
    monkeypatch.setattr(watcher, "socket_bytes", lambda pids: {"a b": next(received)})
    assert watcher.watch(["owner"], until_event=True, stall_min=1, timeout=0.2) is False
    assert "stalled?" not in capsys.readouterr().out


def test_socket_bytes_sums_only_the_jobs_sockets(monkeypatch):
    out = (
        'ESTAB 0 0 10.0.0.2:5000 1.2.3.4:443 users:(("codex",pid=40,fd=9))\n'
        "\t cubic wscale:7,7 bytes_sent:900 bytes_acked:800 bytes_received:5000 segs_out:9\n"
        'ESTAB 0 0 10.0.0.2:5001 1.2.3.4:443 users:(("other",pid=99,fd=3))\n'
        "\t cubic bytes_acked:7 bytes_received:7\n"
    )
    done = watcher.subprocess.CompletedProcess([], 0, out, "")
    monkeypatch.setattr(watcher.subprocess, "run", lambda *a, **k: done)
    assert watcher.socket_bytes({40}) == {"10.0.0.2:5000 1.2.3.4:443": 5800}


def test_a_silent_job_with_idle_processes_is_stalled(monkeypatch, tmp_path, capsys):
    root, job = setup_job(tmp_path)
    os.utime(job / "live.jsonl", (0, 0))
    monkeypatch.setattr(watcher, "JOBS", root)
    monkeypatch.setattr(watcher, "running", lambda state: True)
    clock = itertools.count(1000, 100)
    monkeypatch.setattr(watcher.time, "time", lambda: next(clock))
    monkeypatch.setattr(watcher.time, "sleep", lambda _: None)
    monkeypatch.setattr(watcher, "tree_cpu", lambda pid: (7.0, {1}))  # an app-server waiting on nothing
    monkeypatch.setattr(watcher, "socket_bytes", lambda pids: {"a b": 100})
    assert watcher.watch(["owner"], until_event=True, stall_min=1, timeout=10) is True
    assert "while running (stalled?)" in capsys.readouterr().out


def test_tree_cpu_reads_this_process():
    cpu, pids = watcher.tree_cpu(os.getpid())
    assert cpu >= 0 and os.getpid() in pids
    assert watcher.tree_cpu(None) is None


def test_root_wait_is_shown_without_a_stall_warning(monkeypatch, tmp_path, capsys):
    root, job = setup_job(tmp_path)
    (job / "live.jsonl").write_text('{"kind":"root_wait","level":"info","minutes":20}\n')
    os.utime(job / "live.jsonl", (0, 0))
    monkeypatch.setattr(watcher, "JOBS", root)
    alive = iter([True, True, False])
    monkeypatch.setattr(watcher, "running", lambda state: next(alive, False))
    times = iter([1000, 1100, 1101])
    monkeypatch.setattr(watcher.time, "time", lambda: next(times, 1101))
    monkeypatch.setattr(watcher.time, "sleep", lambda _: None)
    watcher.watch(["owner"], until_event=True, stall_min=1)
    output = capsys.readouterr().out
    assert "status: worker waiting for root" in output
    assert "stalled?" not in output


def test_until_event_returns_when_no_runner_left(monkeypatch, tmp_path, capsys):
    root, _ = setup_job(tmp_path)
    monkeypatch.setattr(watcher, "JOBS", root)
    monkeypatch.setattr(watcher, "running", lambda state: False)
    sleeps = []
    monkeypatch.setattr(watcher.time, "sleep", sleeps.append)
    watcher.watch(["owner"], until_event=True)
    assert len(sleeps) == 4
    assert "watch: no running jobs left, exiting" in capsys.readouterr().out


def test_until_event_waits_for_a_runner_starting_after_watch(monkeypatch, tmp_path, capsys):
    root = tmp_path / "jobs"
    owner = root / "owner"
    owner.mkdir(parents=True)
    job = owner / "worker"
    monkeypatch.setattr(watcher, "JOBS", root)
    monkeypatch.setattr(watcher, "running", lambda state: state.get("runnerPid") == 4321)
    ticks = 0

    def tick(_):
        nonlocal ticks
        ticks += 1
        if ticks == 1:
            job.mkdir()
            (job / "state.json").write_text(json.dumps({"runnerPid": 4321}))
            (job / "live.jsonl").write_text("")
        elif ticks == 2:
            (job / "live.jsonl").write_text('{"kind":"error","level":"urgent","message":"failed"}\n')

    monkeypatch.setattr(watcher.time, "sleep", tick)
    watcher.watch(["owner"], until_event=True)
    assert ticks == 2
    assert "worker: error | failed" in capsys.readouterr().out


def test_acknowledged_utf8_events_stay_read_and_new_jobs_are_picked_up(monkeypatch, tmp_path, capsys):
    root, job = setup_job(tmp_path)
    with (job / "live.jsonl").open("a", encoding="utf-8") as stream:
        stream.write('{"kind":"turn_completed","level":"urgent","text":"old → done"}\n')
    monkeypatch.setattr(watcher, "JOBS", root)
    monkeypatch.setattr(watcher, "running", lambda state: True)
    from agent_bridge.acknowledgements import acknowledge, displayed

    displayed(job, (job / "live.jsonl").stat().st_size)
    acknowledge(job)
    late = root / "owner" / "late"

    def tick(_):
        late.mkdir(exist_ok=True)
        (late / "state.json").write_text("{}")
        (late / "live.jsonl").write_text('{"kind":"message","level":"urgent","text":"new"}\n')

    monkeypatch.setattr(watcher.time, "sleep", tick)
    watcher.watch(["owner"], until_event=True)
    out = capsys.readouterr().out
    assert "old" not in out
    assert "late: message | new" in out


def test_valid_scalar_event_does_not_stop_watch(monkeypatch, tmp_path, capsys):
    root, job = setup_job(tmp_path)
    (job / "live.jsonl").write_text("")
    monkeypatch.setattr(watcher, "JOBS", root)
    alive = iter([True, False])
    monkeypatch.setattr(watcher, "running", lambda state: next(alive, False))
    monkeypatch.setattr(watcher.time, "sleep", lambda _: (job / "live.jsonl").write_text("null\n"))
    watcher.watch(["owner"], until_event=True)
    assert "null" not in capsys.readouterr().out


def test_truncated_log_restarts_from_byte_zero(monkeypatch, tmp_path, capsys):
    root, job = setup_job(tmp_path)
    (job / "live.jsonl").write_text("old\n" * 100)
    monkeypatch.setattr(watcher, "JOBS", root)
    monkeypatch.setattr(watcher, "running", lambda state: True)

    def truncate(_):
        (job / "live.jsonl").write_text('{"kind":"error","level":"urgent","message":"new"}\n')

    monkeypatch.setattr(watcher.time, "sleep", truncate)
    watcher.watch(["owner"], until_event=True)
    assert "worker: error | new" in capsys.readouterr().out


def test_rearmed_watch_replays_all_unacknowledged_and_summarizes_each(monkeypatch, tmp_path, capsys):
    root, job = setup_job(tmp_path)
    other = root / "owner" / "second"
    other.mkdir()
    (other / "state.json").write_text("{}")
    for target, kind in ((job, "turn_completed"), (other, "question")):
        with (target / "live.jsonl").open("a") as stream:
            stream.write(json.dumps({"kind": kind, "at": "2026-10-25T00:00:00Z"}) + "\n")
    monkeypatch.setattr(watcher, "JOBS", root)
    monkeypatch.setattr(watcher, "running", lambda _: False)
    for _ in range(2):
        watcher.watch(["owner"], until_event=True)
        output = capsys.readouterr().out
        assert "owner/worker turn_completed 2026-10-25T00:00:00Z [unacknowledged]" in output
        assert "owner/second question 2026-10-25T00:00:00Z [unacknowledged]" in output


def test_launch_offset_cannot_hide_pending_events(monkeypatch, tmp_path, capsys):
    root, job = setup_job(tmp_path)
    with (job / "live.jsonl").open("a") as stream:
        stream.write('{"kind":"steer_queued"}\n')
    monkeypatch.setattr(watcher, "JOBS", root)
    monkeypatch.setattr(watcher, "running", lambda _: False)
    watcher.watch(["owner"], until_event=True, offsets={job: (job / "live.jsonl").stat().st_size})
    assert "owner/worker steer_queued" in capsys.readouterr().out

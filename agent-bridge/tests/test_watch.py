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


def test_old_utf8_events_stay_read_and_new_jobs_are_picked_up(monkeypatch, tmp_path, capsys):
    root, job = setup_job(tmp_path)
    with (job / "live.jsonl").open("a", encoding="utf-8") as stream:
        stream.write('{"kind":"turn_completed","level":"urgent","text":"old → done"}\n')
    monkeypatch.setattr(watcher, "JOBS", root)
    monkeypatch.setattr(watcher, "running", lambda state: True)
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

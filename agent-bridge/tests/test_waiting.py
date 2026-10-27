import json
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import jsonschema
import pytest

from agent_bridge import assessment, cli, core, status, waiting, watch
from agent_bridge.acknowledgements import event_lines, urgent
from agent_bridge.status_activity import in_flight
from agent_bridge.status_inputs import EventLog
from agent_bridge.status_model import DeclaredWait, InFlight

NOW = 1800000000


def stamp(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()


@pytest.fixture
def world(tmp_path, monkeypatch):
    root = tmp_path / "jobs"
    monkeypatch.setattr(core, "JOBS", root)
    monkeypatch.setattr(cli, "JOBS", root)
    monkeypatch.setattr(watch, "JOBS", root)
    monkeypatch.setattr(status, "running", lambda state: bool(state.get("runnerPid")))
    monkeypatch.setattr(status, "tree_cpu", lambda _: None)
    monkeypatch.setattr(core, "stamp", lambda: stamp(NOW))
    monkeypatch.setattr(cli, "stamp", lambda: stamp(NOW))
    monkeypatch.setattr(status.time, "time", lambda: NOW)
    for name in ("a", "b", "c"):
        job = root / "owner" / name
        job.mkdir(parents=True)
        core.save(job / "state.json", {"backend": "codex", "runnerPid": 42})
        core.append(job / "live.jsonl", {"kind": "turn_started", "at": stamp(NOW - 2000)})
    return root


@pytest.mark.parametrize("mode,age,flight,expected", [
    ("waiting_for_heavy", 9999, True, "known"),
    ("paused", 9999, True, "known"),
    ("retrying", 9999, True, "known"),
    ("blocked_on_question", 9999, True, "known"),
    ("running", 599, True, "known"),
    ("running", 600, True, "long-command"),
    ("running", 1249, False, "known"),
    ("running", 1250, False, "overdue-wait"),
    ("running", 1250, True, "overdue-wait"),
])
def test_one_classification_table(mode, age, flight, expected):
    declaration = DeclaredWait("external", "service response", stamp(NOW - age), 1000)
    active = InFlight("tool-1", "command", stamp(NOW - age), age) if flight else None
    value = assessment.assess(mode, "known wait", 9999, waiting=declaration, in_flight=active,
                              now=NOW, declared_at=NOW - age)
    assert value.state == expected
    assert value.reason
    assert assessment.assess("running", "", 9999, waiting=declaration,
                             in_flight=active, critical=True).state == "known"


def test_plain_silence_and_command_thresholds_are_owned_by_classifier():
    assert assessment.assess("running", "", assessment.SILENCE_SECONDS - 1).state == "ok"
    assert assessment.assess("running", "", assessment.SILENCE_SECONDS).state == "stalled"
    assert assessment.COMMAND_GRACE_SECONDS == 600
    assert assessment.WAIT_GRACE_FACTOR == 1.25


def test_worker_command_round_trip_clear_and_allowlist(world, monkeypatch, capsys):
    monkeypatch.setenv(core.WORKER_FLAG, "1")
    monkeypatch.setenv("AGENT_BRIDGE_JOB", "owner/a")
    monkeypatch.setattr(sys, "argv", ["agent-bridge", "waiting", "--on", "peer", "--peer", "b",
                                     "--for", "20m", "--note", "review reply"])
    cli.main()
    record = core.load_state(world / "owner/a")["waiting"]
    assert waiting.decode(record, "owner", NOW) == DeclaredWait("peer", "review reply", stamp(NOW),
                                                              1200, "owner/b")
    monkeypatch.setattr(sys, "argv", ["agent-bridge", "group", "clear", "owner", "batch"])
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2
    monkeypatch.setattr(sys, "argv", ["agent-bridge", "waiting", "--clear"])
    cli.main()
    assert "waiting" not in core.load_state(world / "owner/a")
    assert "waiting: cleared" in capsys.readouterr().out


@pytest.mark.parametrize("kind", ["command_start", "message", "question", "error", "turn_failed",
                                  "turn_completed", "approval_declined"])
def test_next_activity_or_failure_clears_without_stale_runner_resurrection(world, kind):
    job = world / "owner/a"
    stale = core.load_state(job)
    value = DeclaredWait("command", "build", stamp(NOW), 1200)
    waiting.write(job, value)
    core.save(job / "state.json", stale)
    assert core.load_state(job)["waiting"] == asdict(value)
    stale = core.load_state(job)
    core.log(job, kind, text="activity")
    core.save(job / "state.json", stale)
    assert "waiting" not in core.load_state(job)


def test_declaration_survives_its_own_command_end_and_restart(world):
    job = world / "owner/a"
    waiting.write(job, DeclaredWait("command", "build", stamp(NOW), 1200))
    core.log(job, "command_end")
    one = status.Collector(world).collect(include_quotas=False).jobs[0]
    two = status.Collector(world).collect(include_quotas=False).jobs[0]
    assert one.waiting == two.waiting and one.stall.state == "known"
    schema = json.loads(Path(status.__file__).with_name("status.schema.json").read_text())
    jsonschema.Draft202012Validator(schema).validate(json.loads(json.dumps(
        status.Collector(world).collect(include_quotas=False).to_dict())))


def test_peer_wait_chain_is_directed_bounded_and_does_not_recurse(world):
    for source, target in (("a", "b"), ("b", "c"), ("c", "a")):
        waiting.write(world / f"owner/{source}", DeclaredWait("peer", "reply", stamp(NOW),
                                                            1200, f"owner/{target}"))
    snapshot = status.Collector(world).collect(include_quotas=False)
    assert [j.stall.reason for j in snapshot.jobs] == ["waiting-on owner/b", "waiting-on owner/c",
                                                     "waiting-on owner/a"]
    assert {(e.source, e.target) for e in snapshot.dependencies} == {
        ("owner/a", "owner/b"), ("owner/b", "owner/c"), ("owner/c", "owner/a")}
    for name in ("a", "b", "c"):
        waiting.write(world / f"owner/{name}", DeclaredWait("peer", "reply", stamp(NOW - 1500),
                                                          1200, "owner/b"))
    assert all(j.stall.state == "overdue-wait"
               for j in status.Collector(world, warmup=True).collect(include_quotas=False).jobs)


@pytest.mark.parametrize("patch", [
    {"kind": "forever"}, {"note": "x" * 81}, {"note": "line\nfeed"}, {"note": []},
    {"expected_seconds": True}, {"expected_seconds": 7201}, {"expected_seconds": 0},
    {"declared_at": stamp(NOW + 1)}, {"declared_at": "2026-01-01T00:00:00"},
    {"peer": "other/job"}, {"peer": "owner/../escape"}, {"peer": []},
])
def test_hostile_declarations_are_rejected_without_hiding_job_or_error(world, patch):
    raw = {**asdict(DeclaredWait("peer", "reply", stamp(NOW), 1200)), **patch}
    with pytest.raises((ValueError, TypeError)):
        waiting.decode(raw, "owner", NOW)
    job = world / "owner/a"
    state = core.load_state(job)
    core.atomic_save(job / "state.json", {**state, "waiting": raw})
    core.append(job / "live.jsonl", {"at": stamp(NOW), "kind": "error", "error": "failed"})
    snapshot = status.Collector(world).collect(include_quotas=False)
    assert len(snapshot.jobs) == 3
    assert snapshot.jobs[0].waiting is None
    assert snapshot.wake_events and snapshot.errors


def test_matched_parallel_tools_and_legacy_fifo(world):
    job = world / "owner/a"
    for kind, identity, at in (("command_start", "one", NOW - 700),
                               ("command_start", "two", NOW - 100),
                               ("command_end", "two", NOW - 99)):
        core.append(job / "live.jsonl", {"at": stamp(at), "kind": kind, "tool_use_id": identity})
    log = EventLog("owner/a", "log")
    errors = []
    log.read(job, errors)
    assert not errors
    assert in_flight(log.rows, NOW).age_seconds == 700
    job_view = status.Collector(world).collect(include_quotas=False).jobs[0]
    assert job_view.stall.state == "long-command"
    assert job_view.in_flight.age_seconds == 700
    core.log(job, "command_end")
    assert status.Collector(world).collect(include_quotas=False).jobs[0].in_flight is None


def test_notices_are_information_once_across_watches_concurrency_and_restart(world, monkeypatch, capsys):
    job = world / "owner/a"
    waiting.write(job, DeclaredWait("external", "response", stamp(NOW - 1500), 1200))
    value = status.Collector(world).collect(include_quotas=False).jobs[0].stall
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: waiting.notice(job, value), range(8)))
    assert len([e for _, e in event_lines(job) if e["kind"] == "overdue_wait"]) == 1
    assert status.Collector(world).collect(include_quotas=False).jobs[0].stall.notice_id is None
    for kind in ("overdue_wait", "long_command"):
        assert not urgent({"kind": kind, "level": "urgent"}, include_info=True)
    clock = iter(range(0, 1000, 2))
    monkeypatch.setattr(watch.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(watch.time, "sleep", lambda _: None)
    assert watch.watch(["owner"], until_event=True, timeout=6, include_info=True) is False
    assert capsys.readouterr().out.count(": overdue_wait |") == 1


def test_snapshot_while_runner_saves_does_not_lose_declaration(world):
    job = world / "owner/a"
    stale = core.load_state(job)
    waiting.write(job, DeclaredWait("command", "build", stamp(NOW), 1200))

    def write(_):
        core.save(job / "state.json", stale)

    with ThreadPoolExecutor(max_workers=3) as pool:
        saves = [pool.submit(write, index) for index in range(20)]
        for _ in range(10):
            snapshot = status.Collector(world).collect(include_quotas=False)
            assert snapshot.jobs[0].waiting.note == "build"
        for future in saves:
            future.result()


def test_clear_failure_cannot_prevent_failure_logging(world):
    job = world / "owner/a"
    (job / "state.json").write_text("broken")
    core.log(job, "error", message="native failure")
    assert list(event_lines(job))[-1][1]["message"] == "native failure"

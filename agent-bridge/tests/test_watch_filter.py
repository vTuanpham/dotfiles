import json
import sys

import pytest

from agent_bridge import cli, status, watch
from agent_bridge.acknowledgements import pending, urgent
from agent_bridge.status_model import HeavyQueue, HeavyRequest, HostPressure


@pytest.mark.parametrize("event,wakes", [
    ({"kind": "turn_completed"}, True), ({"kind": "turn_failed"}, True),
    ({"kind": "question"}, True), ({"kind": "error"}, True),
    ({"kind": "message", "text": "URGENT: blocked"}, True),
    ({"kind": "message", "text": "BLOCKING: approval needed"}, True),
    ({"kind": "message", "level": "urgent", "text": "blocked"}, True),
    ({"kind": "message", "blocking": True}, True),
    ({"kind": "message", "text": "waiting for the lock"}, False),
    ({"kind": "message", "text": "progress"}, False),
    ({"kind": "slow", "level": "urgent"}, False),
    ({"kind": "stalled", "level": "urgent"}, False),
    ({"kind": "steer_queued", "level": "urgent"}, False),
])
def test_default_wake_set_and_opt_in(event, wakes):
    assert urgent(event) is wakes
    assert urgent(event, include_info=True) is True


@pytest.mark.parametrize("kind", ["heavy_wait", "retry_wait", "retryable_error", "attempt_failed"])
def test_queue_and_retry_status_never_wake_even_with_info(kind):
    event = {"kind": kind, "level": "urgent"}
    assert urgent(event) is False
    assert urgent(event, include_info=True) is False


@pytest.mark.parametrize("include_info", [False, True])
def test_routine_events_stay_visible_without_default_wake(monkeypatch, tmp_path, capsys, include_info):
    job = tmp_path / "owner/job"
    job.mkdir(parents=True)
    (job / "state.json").write_text("{}")
    (job / "live.jsonl").write_text('{"kind":"message","text":"progress"}\n'
                                    '{"kind":"slow","level":"urgent","message":"slow notice"}\n')
    monkeypatch.setattr(watch, "JOBS", tmp_path)
    monkeypatch.setattr(watch.status, "running", lambda _: True)
    monkeypatch.setattr(watch.status, "tree_cpu", lambda _: None)
    ticks = []

    def tick(_):
        ticks.append(1)
        with (job / "live.jsonl").open("a") as stream:
            stream.write('{"kind":"turn_completed"}\n')

    monkeypatch.setattr(watch.time, "sleep", tick)
    watch.watch(["owner"], until_event=True, include_info=include_info)
    out = capsys.readouterr().out
    assert "progress" in out and "slow notice" in out
    assert len(ticks) == (0 if include_info else 1)
    assert [e["kind"] for _, e in pending(job)] == ([] if include_info else ["turn_completed"])


def test_heavy_queue_is_status_and_suppresses_stall_even_with_info(monkeypatch, tmp_path, capsys):
    job = tmp_path / "owner/job"
    job.mkdir(parents=True)
    (job / "state.json").write_text("{}")
    (job / "live.jsonl").write_text("")
    monkeypatch.setattr(watch, "JOBS", tmp_path)
    monkeypatch.setattr(watch.status, "running", lambda _: True)
    monkeypatch.setattr(status, "collect_host", lambda *_: (
        HostPressure(None, None, None, None, (), "", "test host"),
        HeavyQueue((HeavyRequest("queued", "owner/job", "pytest", 1024, False, "queued", 1, None, True),),
                   False, None, 0, None), None))
    clock = iter([0, 2000, 4000])
    monkeypatch.setattr(watch.time, "time", lambda: next(clock))
    sleeps = []

    def tick(_):
        sleeps.append(1)
        if len(sleeps) == 2:
            with (job / "live.jsonl").open("a") as stream:
                stream.write('{"kind":"turn_completed"}\n')

    monkeypatch.setattr(watch.time, "sleep", tick)
    watch.watch(["owner"], until_event=True, stall_min=1, include_info=True)
    out = capsys.readouterr().out
    assert "waiting for heavy slot" in out and "stalled?" not in out
    events = [json.loads(line) for line in (job / "live.jsonl").read_text().splitlines()]
    assert [event["kind"] for event in events] == ["heavy_wait", "turn_completed"]


@pytest.mark.parametrize("enabled", [False, True])
def test_cli_watch_info_flag_defaults_off(monkeypatch, enabled):
    monkeypatch.setattr(sys, "argv", ["agent-bridge", "watch", "owner", "--until-event",
                                     *(["--include-info"] if enabled else [])])
    seen = []
    monkeypatch.setattr(cli, "watch", lambda *args, **kwargs: seen.append(kwargs) or True)
    cli.main()
    assert seen == [{"include_info": enabled}]

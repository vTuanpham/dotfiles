import json
import sys

import pytest

from agent_bridge import cli
from agent_bridge.acknowledgements import acknowledge, displayed, event_lines, pending, read_owner


def emit(job, kind, **fields):
    with (job / "live.jsonl").open("a") as stream:
        stream.write(json.dumps({"kind": kind, **fields}, ensure_ascii=False) + "\n")
    return (job / "live.jsonl").stat().st_size


def test_ack_only_clears_displayed_events_and_preserves_new_arrivals(tmp_path):
    job = tmp_path / "owner" / "job"
    job.mkdir(parents=True)
    first = emit(job, "message", text="URGENT: décider →")
    acknowledge(job)
    assert len(pending(job)) == 1
    displayed(job, first)
    emit(job, "error")
    acknowledge(job)
    assert [event["kind"] for _, event in pending(job)] == ["error"]


def test_result_acknowledges_only_snapshot_completions(monkeypatch, tmp_path, capsys):
    job = tmp_path / "owner" / "job"
    job.mkdir(parents=True)
    (job / "state.json").write_text("{}")
    (job / "live.jsonl").write_text('not json\nnull\n{"kind":[]}\n')
    emit(job, "question")
    emit(job, "message", text="report")
    emit(job, "turn_completed")
    monkeypatch.delenv("AGENT_BRIDGE_WORKER", raising=False)
    monkeypatch.setattr(cli, "resolve_job", lambda _: job)
    monkeypatch.setattr(sys, "argv", ["agent-bridge", "result", "owner/job"])
    read_result = cli.result_text

    def racing_result(*args):
        result = read_result(*args)
        emit(job, "turn_completed")
        return result

    monkeypatch.setattr(cli, "result_text", racing_result)
    cli.main()
    assert capsys.readouterr().out == "report\n"
    assert [event["kind"] for _, event in pending(job)] == ["question", "turn_completed"]


def test_owner_ack_cli_is_scoped_and_cannot_ack_undisplayed_events(monkeypatch, tmp_path):
    from agent_bridge import watch

    jobs = tmp_path / "jobs"
    for owner in ("one", "two"):
        job = jobs / owner / "job"
        job.mkdir(parents=True)
        (job / "state.json").write_text("{}")
        displayed(job, emit(job, "error"))
    monkeypatch.setattr(watch, "JOBS", jobs)
    monkeypatch.delenv("AGENT_BRIDGE_WORKER", raising=False)
    monkeypatch.setattr(sys, "argv", ["agent-bridge", "ack", "one"])
    cli.main()
    assert pending(jobs / "one" / "job") == []
    assert len(pending(jobs / "two" / "job")) == 1


def test_cursor_resets_for_shortened_or_replaced_logs_and_retains_partial_lines(tmp_path):
    job = tmp_path / "owner" / "job"
    job.mkdir(parents=True)
    end = emit(job, "error", text="long old line" * 20)
    displayed(job, end)
    acknowledge(job)
    (job / "live.jsonl").write_text('{"kind":"question"}\n{"kind":"error"')
    assert [e["kind"] for _, e in pending(job)] == ["question"]
    displayed(job, len('{"kind":"question"}\n'))
    acknowledge(job)
    replacement = job / "new.jsonl"
    replacement.write_text('{"kind":"error","text":"replacement"}\n')
    replacement.replace(job / "live.jsonl")
    assert [e["kind"] for _, e in pending(job)] == ["error"]


def test_malformed_events_do_not_hide_following_urgent_records(tmp_path):
    (tmp_path / "live.jsonl").write_bytes(
        b'null\n{"kind":[]}\n{"kind":3}\n{"kind":"message","text":"\xff"}\n'
        b'{"kind":"question"}\n{"kind":"error"'
    )
    assert [event["kind"] for _, event in event_lines(tmp_path)] == ["question"]


@pytest.mark.parametrize("data", [None, [], {"version": 2, "jobs": {}},
                                  {"version": True, "jobs": {}},
                                  {"version": 1, "jobs": {"job": {"through": -1}}}])
def test_malformed_cursor_fails_without_acknowledging(tmp_path, data):
    (tmp_path / "ack.json").write_text(json.dumps(data))
    with pytest.raises(ValueError, match="invalid owner"):
        read_owner(tmp_path)

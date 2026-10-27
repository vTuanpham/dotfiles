import json
import sys
import threading
from datetime import datetime
from pathlib import Path

import jsonschema
import pytest

from agent_bridge import cli, core, heavy, peers, status, status_model, status_render, watch
from agent_bridge.acknowledgements import acknowledge, displayed, event_lines, urgent
from agent_bridge.status_inputs import agy_quota, codex_quotas
from agent_bridge.status_model import HeavyQueue, HeavyRequest, HostPressure

NOW = "2026-10-27T00:00:00+00:00"
SCHEMA = json.loads(Path(status.__file__).with_name("status.schema.json").read_text())
VALIDATE = jsonschema.Draft202012Validator(SCHEMA, format_checker=jsonschema.FormatChecker())


@pytest.fixture
def world(tmp_path, monkeypatch):
    root = tmp_path / "jobs"
    monkeypatch.setattr(core, "JOBS", root)
    monkeypatch.setattr(cli, "JOBS", root)
    monkeypatch.setattr(watch, "JOBS", root)
    monkeypatch.setattr(status, "running", lambda s: bool(s.get("runnerPid")))
    monkeypatch.setattr(status, "tree_cpu", lambda _: None)
    monkeypatch.setattr(status, "quotas", lambda *_: ())
    monkeypatch.setattr(core, "stamp", lambda: NOW)
    monkeypatch.setattr(status.time, "time", lambda: datetime.fromisoformat(NOW).timestamp())
    return root


def job_at(root, name="owner/a", **state):
    job = root / name
    job.mkdir(parents=True)
    core.save(job / "state.json", {"backend": "codex", "title": "Check status", **state})
    return job


def event(job, kind, **fields):
    core.append(job / "live.jsonl", {"at": NOW, "kind": kind, **fields})


def test_schema_validates_produced_cli_snapshots_and_additive_fields(world, monkeypatch, capsys):
    job = job_at(world)
    event(job, "turn_completed", status="completed")
    monkeypatch.setattr(sys, "argv", ["agent-bridge", "status", "--json"])
    cli.main()
    value = json.loads(capsys.readouterr().out)
    VALIDATE.validate(value)
    assert value["schema_version"] == 1
    assert value["wake_events"][0]["kind"] == "completion_batch"
    value["future"] = {"unrecognized": True}
    value["jobs"][0]["future"] = 1
    VALIDATE.validate(value)
    assert not (job.parent / "ack.json").exists()  # status never displays or acknowledges


@pytest.mark.parametrize(
    "mode,quiet,busy,steps,expected",
    [
        ("waiting_for_heavy", 9000, False, (61, 0, 5), "known"),
        ("paused", 9000, False, (61, 0, 5), "known"),
        ("retrying", 9000, True, (61, 0, 5), "known"),
        ("waiting_for_root", 9000, False, (61, 0, 5), "known"),
        ("blocked_on_question", 9000, False, (61, 0, 5), "known"),
        ("idle", 9000, False, None, "inactive"),
        ("running", 899, False, None, "ok"),
        ("running", 900, False, None, "stalled"),
        ("running", 900, True, None, "ok"),
        ("running", 2700, True, None, "stalled"),
        ("running", 100, False, (61, 0, 5), "slow"),
    ],
)
def test_stall_classification_table(mode, quiet, busy, steps, expected):
    a = status.assess(mode, "known reason", quiet, 900, busy, steps)
    assert a.state == expected and a.reason


def queue(monkeypatch, paused=False):
    request = HeavyRequest("q", "owner/a", "pytest", 1024, False, "queued", 100, None, True)
    monkeypatch.setattr(
        status,
        "collect_host",
        lambda *_: (
            HostPressure(None, None, None, None, (), "", "test host"),
            HeavyQueue((request,), paused, "review" if paused else None, 0, None),
            None,
        ),
    )


@pytest.mark.parametrize("paused,expected", [(False, "waiting_for_heavy"), (True, "paused")])
def test_queued_job_suppresses_old_slow_notice_at_snapshot_boundary(world, monkeypatch, paused, expected):
    job = job_at(world, runnerPid=12)
    event(job, "slow", recentSeconds=61, usualSeconds=0, message="model steps take 61s, usually 0s")
    queue(monkeypatch, paused)
    snapshot = status.Collector().collect()
    assert snapshot.jobs[0].state == expected
    assert snapshot.jobs[0].stall.state == "known"
    assert snapshot.jobs[0].last_message is None
    VALIDATE.validate(json.loads(json.dumps(snapshot.to_dict())))


def test_question_retry_and_root_wait_are_known_states(world):
    job = job_at(world, runnerPid=12)
    event(job, "question", question="Proceed?")
    collector = status.Collector()
    assert collector.collect().jobs[0].state == "blocked_on_question"
    event(job, "question_answered")
    event(job, "root_wait")
    assert collector.collect().jobs[0].state == "waiting_for_root"
    core.save(job / "state.json", {"runnerPid": 12, "retry": {"attempt": 1, "maximum": 4}})
    assert collector.collect().jobs[0].state == "retrying"


def test_peer_round_trip_graph_previews_counts_and_never_wakes(world, monkeypatch, capsys):
    a = job_at(world)
    b = job_at(world, "owner/b")
    collector = status.Collector()
    for text in ("TO b: check the decoder", "TO b: ready → review"):
        core.log(a, "message", text=text)
        core.route_to_peers(a, text)
    core.log(b, "message", text="TO a: reviewed")
    core.route_to_peers(b, "TO a: reviewed")
    snapshot = collector.collect()
    graph = snapshot.peers
    assert graph.nodes == ("owner/a", "owner/b")
    assert [(e.source, e.target, e.count) for e in graph.edges] == [
        ("owner/a", "owner/b", 2),
        ("owner/b", "owner/a", 1),
    ]
    assert graph.recent_messages[1].size == len("ready → review".encode())
    assert len(list((b / "steer").glob("*.md"))) == 2
    assert not snapshot.wake_events
    assert all(not urgent(raw, True) for _, raw in event_lines(a))
    monkeypatch.setattr(watch.time, "sleep", lambda _: None)
    watch.watch(["owner"], until_event=True, include_info=True)
    text = capsys.readouterr().out
    assert "a → b: check the decoder" in text and "b → a: reviewed" in text
    assert "watch: wake events" not in text
    VALIDATE.validate(json.loads(json.dumps(snapshot.to_dict())))


def test_peer_preview_secret_policy(world, monkeypatch):
    a = job_at(world)
    job_at(world, "owner/b")
    monkeypatch.setenv("SERVICE_TOKEN", "example-sensitive-value")
    for text in ("TOKEN=hidden", "example-sensitive-value", "Bearer hidden", "sk-example"):
        core.route_to_peers(a, f"TO b: {text}")
    assert all(m.preview is None for m in status.Collector().collect().peers.recent_messages)
    assert peers.preview("ordinary\nmessage") == "ordinary message"


def test_peer_window_and_bounded_messages(world):
    a = job_at(world)
    job_at(world, "owner/b")
    for i in range(105):
        event(a, "peer_sent", **peers.fields(a, "b", f"message {i}"))
    event(a, "peer_sent", **peers.fields(a, "b", "old"))
    lines = (a / "live.jsonl").read_text().splitlines()
    old = json.loads(lines[-1])
    old["at"] = "2020-01-01T00:00:00Z"
    (a / "live.jsonl").write_text("\n".join(lines[:-1] + [json.dumps(old)]) + "\n")
    graph = status.Collector().collect().peers
    assert len(graph.recent_messages) == 100 and graph.edges[0].count == 105


@pytest.mark.parametrize(
    "raw",
    [
        "null",
        "[]",
        "{broken",
        '{"runnerPid":true}',
        '{"title":5}',
        '{"retry":{"attempt":0,"maximum":4}}',
        '{"memoryMax":"NaN"}',
        '{"cpuQuota":"inf%"}',
        '{"retiredAt":"2026-01-01T00:00:00"}',
    ],
)
def test_hostile_state_is_rejected_without_echo(world, raw):
    job = job_at(world)
    (job / "state.json").write_text(raw)
    snapshot = status.Collector().collect()
    assert not snapshot.jobs and snapshot.errors == ("owner/a: invalid or unreadable state",)


def test_symlinks_malformed_events_and_ack_are_not_guessed(world, tmp_path):
    job = job_at(world)
    event(job, "message", at="2026-01-01T00:00:00", text="invalid time")
    event(job, "message", text={"invalid": "type"})
    event(job, "message", text="valid")
    (job / "live.jsonl").open("a").write('null\n{broken\n{"kind":"message"')
    snapshot = status.Collector().collect()
    assert snapshot.jobs[0].last_message == "valid"
    assert len(snapshot.errors) == 2
    (job.parent / "ack.json").write_text('{"version":1,"jobs":{"a":null}}')
    assert not status.Collector().collect().jobs
    (job.parent / "ack.json").unlink()
    outside = tmp_path / "outside.json"
    outside.write_text('{"title":"outside"}')
    (job / "state.json").unlink()
    (job / "state.json").symlink_to(outside)
    assert not status.Collector().collect().jobs
    (job / "state.json").unlink()
    core.save(job / "state.json", {})
    (job / "live.jsonl").unlink()
    (job / "live.jsonl").symlink_to(outside)
    assert not status.Collector().collect().jobs


def test_concurrent_atomic_states_partial_utf8_events_and_snapshot(world):
    job = job_at(world)
    ready = threading.Event()
    go = threading.Event()

    def writer():
        core.save(job / "state.json", {"backend": "codex", "model": "m"})
        with (job / "live.jsonl").open("ab", buffering=0) as stream:
            raw = (
                json.dumps({"kind": "message", "at": NOW, "text": "ready → review"}, ensure_ascii=False)
                + "\n"
            ).encode()
            stream.write(raw[:-2])
            ready.set()
            go.wait(5)
            stream.write(raw[-2:])
        for i in range(25):
            core.save(job / "state.json", {"backend": "codex", "title": str(i)})
            event(job, "message", text=str(i))

    thread = threading.Thread(target=writer)
    thread.start()
    try:
        assert ready.wait(5)
        collector = status.Collector()
        first = collector.collect()
        assert first.jobs[0].message_count == 0
        go.set()
        for _ in range(25):
            VALIDATE.validate(json.loads(json.dumps(collector.collect().to_dict())))
        thread.join(5)
        assert not thread.is_alive()
        final = collector.collect()
        assert final.jobs[0].message_count == 26
        assert final.jobs[0].last_message == "24"
    finally:
        go.set()
        thread.join(5)


def test_oom_deltas_are_on_the_job_only_with_unique_scope(world, monkeypatch, tmp_path):
    job_at(world, runnerPid=12)
    scope = tmp_path / "codex.slice/job.scope"
    scope.mkdir(parents=True)
    (scope / "memory.current").write_text("100")
    (scope / "memory.events").write_text("oom_kill 2\n")
    monkeypatch.setattr(status, "tree_cpu", lambda _: (1.0, {12}))
    monkeypatch.setattr(status, "socket_bytes", lambda _: {})
    monkeypatch.setattr(status.status_resources, "scopes", lambda _: {scope})
    collector = status.Collector()
    first = collector.collect().jobs[0]
    assert first.oom_kill == 2 and first.oom_kill_delta is None
    (scope / "memory.events").write_text("oom_kill 3\n")
    snapshot = collector.collect()
    assert snapshot.jobs[0].oom_kill_delta == 1
    assert snapshot.pressure.groups[-1].attributed_job == "owner/a"
    job_at(world, "owner/b", runnerPid=13)
    shared = collector.collect()
    assert all(j.oom_kill_delta is None for j in shared.jobs)
    assert shared.jobs[0].oom_kill == 3  # previously observed unique ownership stays recorded
    assert shared.jobs[1].oom_kill is None
    assert not any(g.attributed_job for g in shared.pressure.groups)


def test_renderer_parity_and_ack_semantics(world):
    job = job_at(world, model="gpt-6-sol")
    event(job, "message", text="report")
    event(job, "turn_completed", status="completed")
    collector = status.Collector()
    snapshot = collector.collect(storage=True)
    j = snapshot.jobs[0]
    assert list(status_render.peers(snapshot)) == ["a\tcodex\tgpt-6-sol\tCheck status\tidle"]
    completion = next(e for e in snapshot.events if e.kind == "turn_completed")
    assert status_render.event(j, completion) == "a (Check status): turn_completed completed"
    assert "jobs=1 running=0 unanswered_urgent=0 size=" in next(status_render.owners(snapshot))
    displayed(job, completion.offset)
    assert collector.collect().wake_events
    acknowledge(job)
    assert not collector.collect().wake_events


def test_quota_decoder_parity_freshness_and_hostile_input():
    q = codex_quotas("* 03 account@example.invalid  Plus      0  62%  81%  Now")[0]
    assert [(w.label, w.remaining_percent) for w in q.windows] == [("h", 62), ("w", 81)]
    assert q.freshness == "unknown" and "@" not in str(q)
    unknown = codex_quotas("  04 account@example.invalid  New Plan      0  62%  81%  Now")[0]
    assert unknown.status == "unsupported plan" and unknown.windows == ()
    now = datetime.fromisoformat(NOW).timestamp()
    data = {
        "account": "a1",
        "at": NOW,
        "rows": [
            {
                "group": "Gemini Models",
                "limit": "Five Hour Limit Remaining",
                "remaining": 42,
                "resets": "soon",
            }
        ],
    }
    assert agy_quota(data, now).freshness == "fresh"
    assert agy_quota(data, now + 600).freshness == "fresh"
    assert agy_quota(data, now + 601).freshness == "stale"
    with pytest.raises(ValueError):
        agy_quota({**data, "rows": [{**data["rows"][0], "remaining": True}]}, now)


def test_worker_snapshot_cannot_read_another_owner(world, monkeypatch):
    job_at(world)
    job_at(world, "other/hidden")
    monkeypatch.setenv(core.WORKER_FLAG, "1")
    monkeypatch.setenv("AGENT_BRIDGE_JOB", "owner/a")
    assert [j.id for j in status.Collector().collect().jobs] == ["owner/a"]


def test_oom_history_survives_new_readers_filters_and_runner_exit(world, monkeypatch, tmp_path):
    job = job_at(world, runnerPid=12)
    scope = tmp_path / "job.scope"
    scope.mkdir()
    (scope / "memory.current").write_text("100")
    (scope / "memory.events").write_text("oom_kill 0\n")
    monkeypatch.setattr(status, "tree_cpu", lambda _: (1.0, {12}))
    monkeypatch.setattr(status, "socket_bytes", lambda _: {})
    monkeypatch.setattr(status.status_resources, "scopes", lambda _: {scope})
    status.Collector().collect(["owner"])
    (scope / "memory.events").write_text("oom_kill 1\n")
    assert status.Collector().collect(["owner"]).jobs[0].oom_kill_delta == 1
    status.Collector().collect(["another-owner"])
    core.save(job / "state.json", {})
    after = status.Collector().collect().jobs[0]
    assert not after.running and after.oom_kill == 1 and after.oom_kill_delta is None


def test_malformed_observation_journal_is_rejected_without_overwrite(world):
    job_at(world)
    folder = world.parent / "status"
    folder.mkdir(mode=0o700)
    path = folder / "oom.json"
    value = '{"schema_version":1,"groups":{"bad":{"job":null,"total":true}}}'
    path.write_text(value)
    snapshot = status.Collector().collect()
    assert snapshot.errors == ("OOM observations unavailable",)
    assert snapshot.jobs[0].oom_kill is None and path.read_text() == value


def test_unreadable_heavy_state_cannot_be_misclassified_as_stalled(world):
    job = job_at(world, runnerPid=12)
    event(job, "turn_started", at="2020-01-01T00:00:00Z")
    folder = heavy.prepare()
    (folder / "pause.json").write_text("null")
    snapshot = status.Collector().collect()
    assert snapshot.heavy.error
    assert snapshot.jobs[0].stall.state == "unknown"


def test_retention_snapshot_only_claims_verified_expired_inactive_data(world):
    dates = {"retiredAt": "2020-01-01T00:00:00Z", "purgeAfter": "2020-01-15T00:00:00Z"}
    job_at(world, **dates)
    dirty = job_at(world, "owner/dirty", **dates)
    (dirty / "out/wt").mkdir(parents=True)
    (dirty / "out/wt/.git").write_text("gitdir: missing")
    job_at(world, "owner/live", runnerPid=12, **dates)
    job_at(world, "owner/future", retiredAt=NOW, purgeAfter="2030-01-01T00:00:00Z")
    collector = status.Collector()
    assert collector.collect().retention.eligible is None
    snapshot = collector.collect(storage=True)
    assert snapshot.retention.retired == 4 and snapshot.retention.expired == 3
    assert snapshot.retention.eligible == 1 and snapshot.retention.dirty == 1
    assert [i.name for i in snapshot.retention.items if i.kind == "job"] == ["a"]
    VALIDATE.validate(json.loads(json.dumps(snapshot.to_dict())))


def test_schema_and_model_fields_stay_in_step():
    from dataclasses import fields, is_dataclass

    for name, kind in vars(status_model).items():
        if isinstance(kind, type) and is_dataclass(kind):
            assert {f.name for f in fields(kind)} == set(SCHEMA["$defs"][name]["properties"])


def test_storage_scan_racing_file_deletion_is_unknown_not_a_failed_snapshot(world, monkeypatch):
    job_at(world)

    def vanished(_):
        raise FileNotFoundError("file removed during scan")

    monkeypatch.setattr(status, "tree_size", vanished)
    snapshot = status.Collector().collect(storage=True)
    assert snapshot.jobs and snapshot.owners[0].size_bytes is None
    assert "owner: storage size unavailable" in snapshot.errors

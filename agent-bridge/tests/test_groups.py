import importlib.util
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from agent_bridge import cli, core, groups, status, watch
from agent_bridge.acknowledgements import acknowledge, displayed
from agent_bridge.status_model import WakePolicy


@pytest.fixture
def world(tmp_path, monkeypatch):
    root = tmp_path / "jobs"
    monkeypatch.setattr(core, "JOBS", root)
    monkeypatch.setattr(cli, "JOBS", root)
    monkeypatch.setattr(watch, "JOBS", root)
    monkeypatch.setattr(groups, "DEFAULT_POLICY", WakePolicy())
    monkeypatch.setattr(status, "running", lambda s: bool(s.get("runnerPid")))
    monkeypatch.setattr(status, "tree_cpu", lambda _: None)
    clock = [2000000000.0]
    monkeypatch.setattr(status.time, "time", lambda: clock[0])
    monkeypatch.setattr(core, "stamp", lambda: groups.iso(clock[0]))
    return root, clock


def job(root, label="owner/a", running=False):
    path = root / label
    path.mkdir(parents=True)
    core.save(path / "state.json", {"backend": "codex", "runnerPid": 123 if running else None})
    return path


def event(path, kind="turn_completed", **fields):
    core.log(path, kind, **fields)


def collect(root):
    return status.Collector(root).collect(include_quotas=False)


def test_default_settle_coalesces_without_repeating_on_watch_restart(world):
    root, clock = world
    a, b = job(root), job(root, "owner/b")
    event(a)
    first = collect(root)
    assert not first.wake_events and first.unacknowledged_completions == 1
    assert first.groups[0].policy.settle_seconds == 60
    assert first.groups[0].policy.remind_seconds == 900
    clock[0] += 30
    event(b)
    assert not collect(root).wake_events
    clock[0] += 30
    ready = collect(root)
    assert len(ready.wake_events) == 1
    notice = ready.wake_events[0]
    assert notice.jobs == ("owner/a", "owner/b")
    groups.seen(a.parent, notice.id)
    again = collect(root)
    assert not again.wake_events and len(again.group_events) == 1
    assert again.unacknowledged_completions == 2


@pytest.mark.parametrize("policy", ["each", "all", "quiet"])
@pytest.mark.parametrize(
    "kind,fields",
    [
        ("turn_failed", {}),
        ("question", {}),
        ("error", {}),
        ("approval_declined", {}),
        ("message", {"text": "URGENT: help"}),
        ("message", {"text": "BLOCKING: help"}),
        ("turn_completed", {"status": "failed"}),
        ("turn_completed", {"error": "failed"}),
    ],
)
def test_policy_never_hides_critical_events_and_flushes_completions(world, policy, kind, fields):
    root, _ = world
    a, b = job(root), job(root, "owner/b")
    groups.configure(a.parent, "crew", WakePolicy(wake=policy), ["a", "b"])
    event(a)
    assert not collect(root).wake_events
    event(b, kind, **fields)
    snapshot = collect(root)
    assert any(e.kind == kind for e in snapshot.wake_events)
    assert any("owner/a" in n.jobs for n in snapshot.group_events if n.wakes)


def test_all_waits_for_declared_members_failure_counts_and_max_wait_is_partial(world):
    root, clock = world
    a = job(root)
    groups.configure(a.parent, "crew", WakePolicy(wake="all", max_wait_seconds=120), ["a", "b"])
    event(a)
    partial = collect(root)
    assert partial.groups[0].done == 1 and partial.groups[0].total == 2
    assert not partial.wake_events
    clock[0] += 120
    partial = collect(root)
    assert partial.group_events[0].kind == "group_partial"
    assert partial.group_events[0].missing == ("owner/b",)
    groups.seen(a.parent, partial.group_events[0].id)
    b = job(root, "owner/b")
    event(b)
    assert not collect(root).wake_events  # a late member cannot emit a second all wake for this batch


def test_all_once_survives_crash_and_repeated_configuration(world):
    root, _ = world
    a, b = job(root), job(root, "owner/b")
    policy = WakePolicy(wake="all")
    groups.configure(a.parent, "crew", policy, ["a", "b"])
    event(a)
    assert not collect(root).wake_events
    event(b)
    first = collect(root)
    notice = first.group_events[0]
    assert first.groups[0].done == 2 and len(first.wake_events) == 1
    groups.configure(a.parent, "crew", policy, ["a", "b"])
    assert collect(root).group_events[0].id == notice.id
    groups.seen(a.parent, notice.id)
    assert not collect(root).wake_events


def test_default_reminder_once_clears_on_ack_without_waking_even_with_info(world, monkeypatch, capsys):
    root, clock = world
    a = job(root)
    groups.configure(a.parent, "crew", WakePolicy(wake="quiet"), ["a"])
    event(a)
    clock[0] += 899
    assert not collect(root).group_events
    clock[0] += 1
    snapshot = collect(root)
    reminder = snapshot.group_events[0]
    assert reminder.kind == "completion_reminder" and not reminder.wakes and not reminder.informational
    assert snapshot.oldest_unacknowledged_completion_age_seconds == 900
    monkeypatch.setattr(watch.time, "sleep", lambda _: None)
    watch.watch(["owner"], until_event=True, include_info=True)
    assert "completion_reminder" in capsys.readouterr().out
    assert not collect(root).wake_events
    acknowledge(a)
    assert not collect(root).group_events and collect(root).unacknowledged_completions == 0


def test_optional_reminder_backoff(world):
    root, clock = world
    a = job(root)
    groups.configure(a.parent, "crew", WakePolicy(wake="quiet", repeat_reminders=True), ["a"])
    event(a)
    clock[0] += 900
    first = collect(root).group_events[0]
    groups.seen(a.parent, first.id)
    clock[0] += 1799
    assert len(collect(root).group_events) == 1
    clock[0] += 1
    assert len(collect(root).group_events) == 2


@pytest.mark.parametrize(
    "raw",
    [
        "[]",
        "null",
        "{broken",
        '{"version":true}',
        '{"version":1,"policies":{"crew":{"wake":"never"}},"members":{}}',
    ],
)
def test_corrupt_policy_falls_back_to_each(world, raw):
    root, clock = world
    a = job(root)
    (a.parent / "groups.json").write_text(raw)
    event(a)
    clock[0] += 60
    snapshot = collect(root)
    assert snapshot.groups[0].policy.wake == "each" and snapshot.wake_events
    assert snapshot.errors


def test_workers_cannot_change_policy_or_membership_even_via_direct_api(world, monkeypatch):
    root, _ = world
    a = job(root)
    monkeypatch.setenv(core.WORKER_FLAG, "1")
    for call in (
        lambda: groups.configure(a.parent, "crew", WakePolicy()),
        lambda: groups.assign(a, "crew"),
        lambda: groups.clear(a.parent, "crew"),
    ):
        with pytest.raises(RuntimeError, match="delegated workers"):
            call()
    assert not (a.parent / "groups.json").exists()
    monkeypatch.setattr(sys, "argv", ["agent-bridge", "group", "set", "owner", "crew", "--wake", "all"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2


def test_oom_is_urgent_and_flushes_held_results(world):
    root, clock = world
    a = job(root)
    event(a)
    snapshot = collect(root)
    job_value = replace(snapshot.jobs[0], oom_kill=1, oom_kill_delta=1)
    native = list(snapshot.events)
    _, _, _, notices = groups.evaluate(a.parent, [job_value], native, clock[0], [])
    assert any(n.kind == "oom_kill" and n.wakes for n in notices)
    assert any(n.kind == "completion_batch" and "owner/a" in n.jobs for n in notices)


def hook_module():
    path = Path(__file__).parents[2] / "claude/.claude/hooks/bridge-stop.py"
    spec = importlib.util.spec_from_file_location("bridge_stop", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize(
    "change,blocked",
    [
        ({}, True),
        ({"agent_id": "subagent"}, False),
        ({"hook_event_name": "SubagentStop"}, False),
        ({"stop_hook_active": True}, False),
        ({"last_assistant_message": "Which option?"}, False),
        ({"last_assistant_message": "Please confirm the choice."}, False),
    ],
)
def test_stop_hook_decision_table_and_no_loop(world, tmp_path, change, blocked):
    root, _ = world
    a = job(root, running=True)
    core.save(a.parent / "root.json", {"at": core.stamp(), "backend": "claude", "session_id": "session"})
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text("")
    payload = {
        "hook_event_name": "Stop",
        "session_id": "session",
        "stop_hook_active": False,
        "last_assistant_message": "Done.",
        "transcript_path": str(transcript),
        **change,
    }
    module = hook_module()
    snapshot = json.loads(json.dumps(collect(root).to_dict()))
    first = module.decide(payload, snapshot, tmp_path / "guard")
    assert bool(first) is blocked
    assert module.decide(payload, snapshot, tmp_path / "guard") is None


def test_stop_guard_scope_questions_active_watch_empty_and_errors(world, tmp_path):
    root, _ = world
    a = job(root)
    core.save(a.parent / "root.json", {"at": core.stamp(), "backend": "claude", "session_id": "session"})
    event(a)
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(
        json.dumps({"message": {"content": [{"type": "tool_use", "name": "AskUserQuestion", "id": "ask"}]}})
        + "\n"
    )
    payload = {
        "hook_event_name": "Stop",
        "session_id": "session",
        "last_assistant_message": "Done.",
        "transcript_path": str(transcript),
    }
    module = hook_module()
    snap = json.loads(json.dumps(collect(root).to_dict()))
    assert module.decide(payload, snap, tmp_path / "guard") is None
    transcript.write_text("")
    snap["owners"][0]["active_watch"] = True
    assert module.decide(payload, snap, tmp_path / "guard") is None
    snap["owners"][0]["active_watch"] = False
    snap["owners"][0]["root_session_id"] = "another-session"
    assert module.decide(payload, snap, tmp_path / "guard") is None
    snap["owners"][0]["root_session_id"] = "session"
    snap["errors"] = ["unavailable"]
    assert module.decide(payload, snap, tmp_path / "guard") is None
    displayed(a, (a / "live.jsonl").stat().st_size)
    acknowledge(a)
    snap = json.loads(json.dumps(collect(root).to_dict()))
    assert module.decide(payload, snap, tmp_path / "guard") is None


def test_concurrent_watches_claim_a_batch_once(world):
    from concurrent.futures import ThreadPoolExecutor

    root, clock = world
    a = job(root)
    event(a)
    clock[0] += 60
    notice = collect(root).group_events[0]
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: groups.seen(a.parent, notice.id), range(2)))
    assert sorted(results) == [False, True]


def test_cli_group_commands_and_start_resume_keep_membership_out_of_worker_state(
    world, tmp_path, monkeypatch
):
    root, _ = world
    prompt = tmp_path / "prompt.md"
    prompt.write_text("Check the fixture.")
    monkeypatch.setattr(cli.reference, "warning", lambda: None)
    monkeypatch.setattr(cli.codex, "active_account", lambda: "")
    monkeypatch.setattr(cli.resources, "validate_caps", lambda *_: None)
    monkeypatch.setattr(cli, "linger", lambda *_: None)
    monkeypatch.setattr(cli.codex, "run", lambda path, *args, **kwargs: event(path))

    def command(*args):
        monkeypatch.setattr(sys, "argv", ["agent-bridge", *args])
        cli.main()

    command("group", "set", "owner", "crew", "--wake", "all", "--members", "a")
    command(
        "start",
        "owner/a",
        "--backend",
        "codex",
        "--title",
        "Test group",
        "--cwd",
        str(tmp_path),
        "--sandbox",
        "read-only",
        "--group",
        "crew",
        "--prompt-file",
        str(prompt),
    )
    path = root / "owner/a"
    state = core.load_state(path)
    state["group"] = "untrusted"
    core.save(path / "state.json", state)
    assert collect(root).jobs[0].group == "crew"
    command("resume", "owner/a", "--group", "second")
    assert collect(root).jobs[0].group == "second"
    assert not (path.parent / "groups.json").stat().st_mode & 0o077
    command("group", "clear", "owner", "crew")
    command("group", "list", "owner")
    command("group", "unassign", "owner/a")
    assert collect(root).jobs[0].group is None


def test_active_watch_is_a_kernel_lock_not_a_stale_file(world):
    import fcntl

    root, _ = world
    path = job(root)
    with (path.parent / "watch.lock").open("a") as stream:
        assert not collect(root).owners[0].active_watch
        fcntl.flock(stream, fcntl.LOCK_SH)
        assert collect(root).owners[0].active_watch
    assert not collect(root).owners[0].active_watch


def test_stop_hook_main_is_disabled_or_fail_open_on_any_error(tmp_path, monkeypatch, capsys):
    import io

    module = hook_module()

    def failed(*args, **kwargs):
        raise TimeoutError("fixture failure")

    monkeypatch.setattr(module.subprocess, "run", failed)
    for raw in ("null", "{broken", '{"hook_event_name":"Stop"}'):
        monkeypatch.setattr(sys, "stdin", io.StringIO(raw))
        module.main()
        assert capsys.readouterr().out == ""
    monkeypatch.setenv("AGENT_BRIDGE_STOP_GUARD", "0")
    monkeypatch.setattr(sys, "stdin", io.StringIO("not JSON"))
    module.main()
    assert capsys.readouterr().out == ""

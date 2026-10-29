import fcntl
import json
import os
import threading

import pytest

from agent_bridge import cli, core, groups, owner_binding, status, watch
from agent_bridge.status_model import WakePolicy


def bind(owner, backend, session_id):
    owner_binding.record(owner, {"backend": backend, "session_id": session_id})


def test_handoff_is_locked_and_stale_root_cannot_rebind(tmp_path):
    owner = tmp_path / "owner"
    owner.mkdir()
    old = {"backend": "claude", "session_id": "old"}
    new = {"backend": "codex", "session_id": "new"}
    bind(owner, **old)
    inside, release = threading.Event(), threading.Event()

    def old_write():
        with owner_binding.access(owner, old):
            inside.set()
            assert release.wait(2)

    worker = threading.Thread(target=old_write)
    worker.start()
    assert inside.wait(2)
    handoff_done = threading.Event()

    def transfer():
        owner_binding.handoff(owner, new)
        handoff_done.set()

    handoff = threading.Thread(target=transfer)
    handoff.start()
    release.set()
    worker.join(2)
    handoff.join(2)
    assert handoff_done.is_set()
    assert owner_binding.known(owner_binding.read(owner)) == new
    with pytest.raises(owner_binding.RootMismatch):
        with owner_binding.access(owner, old):
            pytest.fail("stale root entered the owner mutation section")


def test_runner_start_releases_handoff_guard_before_the_backend_runs(tmp_path):
    owner = tmp_path / "owner"
    job = owner / "job"
    job.mkdir(parents=True)
    state = job / "state.json"
    core.save(state, {"version": 1, "backend": "codex"})
    old = {"backend": "claude", "session_id": "old"}
    new = {"backend": "codex", "session_id": "new"}
    bind(owner, **old)
    handoff_done = threading.Event()

    def transfer():
        owner_binding.handoff(owner, new)
        handoff_done.set()

    with owner_binding.access(owner, old, start=True):
        handoff = threading.Thread(target=transfer)
        handoff.start()
        core.runner_started({"version": 1, "backend": "codex"}, state)
        assert handoff_done.wait(2), "handoff must proceed once runner_started persists the PID"
    handoff.join(2)
    assert owner_binding.known(owner_binding.read(owner)) == new


def test_parent_close_does_not_unlock_a_delayed_forked_runner(tmp_path):
    owner, job = tmp_path / "owner", tmp_path / "owner" / "job"
    job.mkdir(parents=True)
    state_path = job / "state.json"
    core.save(state_path, {"version": 1, "backend": "codex"})
    old = {"backend": "codex", "session_id": "old"}
    new = {"backend": "claude", "session_id": "new"}
    bind(owner, **old)

    go_read, go_write = os.pipe()
    child_started_read, child_started_write = os.pipe()
    guard = owner_binding.access(owner, old, start=True)
    guard.__enter__()
    child = os.fork()
    if child == 0:
        os.close(go_write)
        os.close(child_started_read)
        try:
            os.read(go_read, 1)
            core.runner_started({"version": 1, "backend": "codex"}, state_path)
            os.write(child_started_write, b"1")
        finally:
            os._exit(0)

    os.close(go_read)
    os.close(child_started_write)
    guard.__exit__(None, None, None)  # the detached parent timed out while the child is still starting
    handoff_done, transfer_error = threading.Event(), []

    def transfer():
        try:
            owner_binding.handoff(owner, new)
        except Exception as error:
            transfer_error.append(error)
        finally:
            handoff_done.set()

    handoff = threading.Thread(target=transfer)
    handoff.start()
    try:
        probe = os.open(owner / "root.lock", os.O_RDWR | os.O_NOFOLLOW)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(probe)
        assert not handoff_done.is_set()
        os.write(go_write, b"1")
        assert os.read(child_started_read, 1) == b"1"
        assert handoff_done.wait(2)
        assert not transfer_error
    finally:
        os.close(go_write)
        os.close(child_started_read)
        os.waitpid(child, 0)
        handoff.join(2)
    assert owner_binding.known(owner_binding.read(owner)) == new


def test_cli_keeps_handoff_locked_until_start_runner_is_registered(monkeypatch, tmp_path):
    jobs = tmp_path / "jobs"
    owner, job = jobs / "owner", jobs / "owner" / "worker"
    job.mkdir(parents=True)
    (job / "prompt.md").write_text("run fixture")
    monkeypatch.setattr(cli, "JOBS", jobs)
    monkeypatch.setattr(core, "JOBS", jobs)
    monkeypatch.setenv("CODEX_THREAD_ID", "old-root")
    monkeypatch.delenv("CLAUDECODE", raising=False)
    monkeypatch.setattr(cli.codex, "active_account", lambda: "")
    entered, start_backend, registered, finish_backend = (threading.Event() for _ in range(4))
    failures = []

    def backend_run(path, state, state_path, prompt, resume=False, compact=False):
        entered.set()
        assert start_backend.wait(2)
        core.runner_started(state, state_path)
        registered.set()
        assert finish_backend.wait(2)

    monkeypatch.setattr(cli.codex, "run", backend_run)
    monkeypatch.setattr(
        cli.sys,
        "argv",
        [
            "agent-bridge",
            "start",
            "owner/worker",
            "--backend",
            "codex",
            "--title",
            "Test worker",
            "--cwd",
            str(tmp_path),
            "--sandbox",
            "read-only",
        ],
    )

    def start():
        try:
            cli.main()
        except BaseException as error:
            failures.append(error)

    runner = threading.Thread(target=start)
    runner.start()
    assert entered.wait(2)
    owner_lock = os.open(owner / "root.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        with pytest.raises(BlockingIOError):
            fcntl.flock(owner_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

        transferred = threading.Event()

        def transfer():
            owner_binding.handoff(owner, {"backend": "codex", "session_id": "new-root"})
            transferred.set()

        handoff = threading.Thread(target=transfer)
        handoff.start()
        start_backend.set()
        assert registered.wait(2)
        assert transferred.wait(2), "handoff waits for state save, then proceeds while the worker runs"
        assert owner_binding.known(owner_binding.read(owner)) == {
            "backend": "codex",
            "session_id": "new-root",
        }
        finish_backend.set()
        runner.join(2)
        handoff.join(2)
        assert not runner.is_alive() and not handoff.is_alive() and not failures
    finally:
        start_backend.set()
        finish_backend.set()
        os.close(owner_lock)


def test_unknown_root_preserves_known_binding_and_legacy_files_can_be_claimed(tmp_path):
    owner = tmp_path / "owner"
    owner.mkdir()
    current = {"backend": "claude", "session_id": "current"}
    bind(owner, **current)
    before = owner_binding.read(owner)
    owner_binding.record(owner)
    assert owner_binding.read(owner) == before

    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "root.json").write_text(json.dumps({"at": "2026-10-27T00:00:00+00:00", "harness": "unknown"}))
    owner_binding.record(legacy, current)
    assert owner_binding.known(owner_binding.read(legacy)) == current


def test_stale_steer_after_handoff_does_not_write_job_history(monkeypatch, tmp_path):
    owner = tmp_path / "jobs" / "owner"
    job = owner / "job"
    job.mkdir(parents=True)
    monkeypatch.setattr(cli, "JOBS", tmp_path / "jobs")
    monkeypatch.setattr(core, "JOBS", tmp_path / "jobs")
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "old-root")
    core.save(job / "state.json", {"version": 1, "backend": "codex", "runnerPid": None})
    cli.record_root(job)

    monkeypatch.setenv("CODEX_THREAD_ID", "new-root")
    monkeypatch.delenv("CLAUDECODE")
    monkeypatch.setattr(cli.sys, "argv", ["agent-bridge", "handoff", "owner"])
    cli.main()

    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.delenv("CODEX_THREAD_ID")
    monkeypatch.setattr(cli.sys, "argv", ["agent-bridge", "steer", "owner/job", "must not land"])
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 1
    assert list((job / "steer").glob("[0-9]*.md")) == []
    assert not any(event.get("kind") == "root_steer" for event in cli.events(job))
    assert owner_binding.known(owner_binding.read(owner)) == {"backend": "codex", "session_id": "new-root"}


def test_stale_watch_cannot_claim_or_native_wake_after_handoff(monkeypatch, tmp_path):
    jobs = tmp_path / "jobs"
    owner, job = jobs / "owner", jobs / "owner" / "job"
    job.mkdir(parents=True)
    monkeypatch.setattr(watch, "JOBS", jobs)
    monkeypatch.setattr(core, "JOBS", jobs)
    core.save(job / "state.json", {"version": 1, "backend": "codex", "runnerPid": None})
    core.log(job, "turn_completed")
    groups.configure(owner, "crew", WakePolicy(settle_seconds=0), ["job"])
    notice = status.Collector(jobs).collect(include_quotas=False).group_events[0]
    owner_binding.handoff(owner, {"backend": "claude", "session_id": "new-root"})

    class Delivery:
        calls = []

        def deliver(self, owners, reason, scheduled=False):
            self.calls.append((owners, reason))

    delivery = Delivery()
    monkeypatch.setattr(watch.root_wake, "prepare", lambda owners: delivery)
    monkeypatch.setenv("CODEX_THREAD_ID", "old-codex-root")
    monkeypatch.delenv("CLAUDECODE", raising=False)
    assert watch.watch(["owner"], until_event=True) is True
    after = status.Collector(jobs).collect(include_quotas=False)
    assert after.wake_events[0].id == notice.id
    assert not after.group_events[0].seen
    assert delivery.calls == []


def test_rootless_watch_can_read_but_not_claim_a_bound_owners_notice(monkeypatch, tmp_path):
    jobs = tmp_path / "jobs"
    owner, job = jobs / "owner", jobs / "owner" / "job"
    job.mkdir(parents=True)
    monkeypatch.setattr(watch, "JOBS", jobs)
    monkeypatch.setattr(core, "JOBS", jobs)
    core.save(job / "state.json", {"version": 1, "backend": "codex", "runnerPid": None})
    core.log(job, "turn_completed")
    groups.configure(owner, "crew", WakePolicy(settle_seconds=0), ["job"])
    owner_binding.handoff(owner, {"backend": "codex", "session_id": "known-root"})
    monkeypatch.delenv("CLAUDECODE", raising=False)
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    monkeypatch.delenv("AGENT_BRIDGE_ROOT_HARNESS", raising=False)
    monkeypatch.delenv("AGENT_BRIDGE_ROOT_SESSION", raising=False)

    assert watch.watch(["owner"], until_event=True) is True
    pending = status.Collector(jobs).collect(include_quotas=False)
    assert pending.wake_events[0].kind == "completion_batch"
    assert not pending.group_events[0].seen


def test_mid_snapshot_handoff_skips_one_owner_and_keeps_watching_the_other(monkeypatch, tmp_path):
    jobs = tmp_path / "jobs"
    owners = [jobs / name for name in ("a", "b")]
    for owner in owners:
        job = owner / "job"
        job.mkdir(parents=True)
        core.save(
            job / "state.json",
            {
                "version": 1,
                "backend": "codex",
                "runnerPid": os.getpid(),
            },
        )
        core.log(job, "question", level="urgent", text="needs a decision")
        owner_binding.record(owner, {"backend": "codex", "session_id": "old-root"})
    monkeypatch.setattr(watch, "JOBS", jobs)
    monkeypatch.setattr(core, "JOBS", jobs)
    monkeypatch.setenv("CODEX_THREAD_ID", "old-root")
    monkeypatch.delenv("CLAUDECODE", raising=False)

    class Delivery:
        calls = []

        def deliver(self, owners, reason, scheduled=False):
            self.calls.append((owners, reason))

    delivery = Delivery()
    monkeypatch.setattr(watch.root_wake, "prepare", lambda owners: delivery)
    render = watch.status_render.job_status
    handed_off = False

    def render_with_handoff(job):
        nonlocal handed_off
        if job.owner == "a" and not handed_off:
            owner_binding.handoff(owners[0], {"backend": "claude", "session_id": "new-root"})
            handed_off = True
        return render(job)

    monkeypatch.setattr(watch.status_render, "job_status", render_with_handoff)
    assert watch.watch(["a", "b"], until_event=True) is True
    assert handed_off
    assert delivery.calls == [(["b"], "event")]
    assert owner_binding.known(owner_binding.read(owners[0])) == {
        "backend": "claude",
        "session_id": "new-root",
    }


def test_current_root_watch_still_delivers_matching_owner(monkeypatch, tmp_path):
    jobs = tmp_path / "jobs"
    owner, job = jobs / "owner", jobs / "owner" / "job"
    job.mkdir(parents=True)
    monkeypatch.setattr(watch, "JOBS", jobs)
    monkeypatch.setattr(core, "JOBS", jobs)
    core.save(job / "state.json", {"version": 1, "backend": "codex", "runnerPid": None})
    core.log(job, "turn_completed")
    groups.configure(owner, "crew", WakePolicy(settle_seconds=0, remind_seconds=None), ["job"])
    owner_binding.handoff(owner, {"backend": "codex", "session_id": "current-root"})

    class Delivery:
        calls = []

        def deliver(self, owners, reason, scheduled=False):
            self.calls.append((owners, reason))

    delivery = Delivery()
    monkeypatch.setattr(watch.root_wake, "prepare", lambda owners: delivery)
    monkeypatch.setenv("CODEX_THREAD_ID", "current-root")
    monkeypatch.delenv("CLAUDECODE", raising=False)
    assert watch.watch(["owner"], until_event=True) is True
    assert delivery.calls == [(["owner"], "event")]
    assert not status.Collector(jobs).collect(include_quotas=False).wake_events

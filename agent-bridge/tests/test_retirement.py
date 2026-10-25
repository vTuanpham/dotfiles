import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import pytest

from agent_bridge import cli, core, retirement, watch


@pytest.fixture
def world(tmp_path, monkeypatch):
    jobs = tmp_path / "jobs"
    for module in (cli, core, watch):
        monkeypatch.setattr(module, "JOBS", jobs)
    monkeypatch.setattr(cli, "ARCHIVE", tmp_path / "archive.jsonl")
    monkeypatch.delenv(core.WORKER_FLAG, raising=False)
    monkeypatch.setattr(cli, "linger", lambda *args: None)
    return jobs


def job_at(jobs, name="owner/job", **fields):
    job = jobs / name
    job.mkdir(parents=True)
    core.save(job / "state.json", {"backend": "codex", "threadId": "original-thread", **fields})
    (job / "prompt.md").write_text("original brief")
    core.log(job, "message", text="original report")
    return job


def command(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["agent-bridge", *args])
    cli.main()


@pytest.mark.parametrize("backend,key", [
    ("codex", "threadId"), ("claude", "sessionId"),
    ("agy", "conversationId"), ("opencode", "sessionId"),
])
def test_restore_resume_preserves_native_session_and_home(world, monkeypatch, capsys, backend, key):
    job = job_at(world, backend=backend, **{key: "original-session"})
    native = job / "home/threads/original"
    native.parent.mkdir(parents=True)
    native.write_bytes(b"native session data")
    original = core.load_state(job)
    command(monkeypatch, "retire", "owner/job", "--keep-days", "7")
    retired = core.load_state(job)
    assert (datetime.fromisoformat(retired["purgeAfter"])
            - datetime.fromisoformat(retired["retiredAt"])) == timedelta(days=7)
    assert native.read_bytes() == b"native session data"
    assert all(retired[k] == value for k, value in original.items())
    assert list(watch.job_dirs(["owner", "owner/job"])) == []
    assert cli.session_bindings()["sessions"] == []
    capsys.readouterr()
    command(monkeypatch, "peers", "owner/job")
    assert capsys.readouterr().out == ""
    command(monkeypatch, "owners")
    assert "jobs=0 running=0 unanswered_urgent=0 size=0B" in capsys.readouterr().out
    monkeypatch.setattr(watch.time, "sleep", lambda _: None)
    command(monkeypatch, "watch", "owner/job", "--until-event")
    assert "original report" not in capsys.readouterr().out
    command(monkeypatch, "result", "owner/job")
    assert "original report" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        command(monkeypatch, "resume", "owner/job")
    assert "job is retired" in capsys.readouterr().err
    command(monkeypatch, "retire", "owner/job")
    assert core.load_state(job) == retired  # idempotent: do not extend retention
    assert len(cli.ARCHIVE.read_text().splitlines()) == 1
    command(monkeypatch, "restore", "owner/job")
    assert core.load_state(job) == original
    assert list(watch.job_dirs(["owner"])) == [job]
    assert cli.session_bindings()["sessions"][0]["session_id"] == "original-session"
    calls = []

    def run(actual_job, state, path, prompt, resume=False):
        assert actual_job == job and resume and state[key] == "original-session"
        assert native.read_bytes() == b"native session data"
        calls.append(state[key])

    monkeypatch.setattr(cli.BACKENDS[backend], "run", run)
    if backend == "agy":
        monkeypatch.setattr(cli.agy, "fallback", lambda *args: None)
    command(monkeypatch, "resume", "owner/job")
    assert calls == ["original-session"]


def test_purge_window_and_legacy_jobs(world, monkeypatch, capsys):
    active = job_at(world, "owner/legacy")
    future = job_at(world, "owner/future")
    expired = job_at(world, "owner/expired")
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(retirement, "stamp", lambda: (now - timedelta(days=15)).isoformat())
    command(monkeypatch, "retire", "owner/expired")
    assert datetime.fromisoformat(core.load_state(expired)["purgeAfter"]) == now - timedelta(days=1)
    monkeypatch.setattr(retirement, "stamp", lambda: now.isoformat())
    command(monkeypatch, "retire", "owner/future")
    with pytest.raises(SystemExit):
        command(monkeypatch, "purge", "owner/future")
    assert "not eligible" in capsys.readouterr().err
    command(monkeypatch, "purge")
    assert active.exists() and future.exists() and not expired.exists()
    command(monkeypatch, "result", "owner/expired")
    assert "original report" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        command(monkeypatch, "restore", "owner/expired")
    assert "purged; cannot restore" in capsys.readouterr().err
    assert not expired.exists()


def test_immediate_purge_keeps_archive_and_old_archives_stay_readable(world, monkeypatch, capsys):
    job = job_at(world)
    command(monkeypatch, "retire", "owner/job", "--purge")
    assert not job.exists()
    command(monkeypatch, "result", "owner/job")
    assert "original report" in capsys.readouterr().out
    cli.ARCHIVE.write_text('{"job":"older/deleted","at":"old","final":"old report"}\n{broken\n')
    command(monkeypatch, "result", "older/deleted")
    assert "old report" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        command(monkeypatch, "restore", "older/deleted")
    assert "purged; cannot restore" in capsys.readouterr().err


@pytest.mark.parametrize("fields", [
    {"retiredAt": "bad", "purgeAfter": "2020-01-01T00:00:00+00:00"},
    {"retiredAt": "2020-01-01T00:00:00", "purgeAfter": "2020-01-02T00:00:00"},
    {"retiredAt": "2020-01-02T00:00:00+00:00", "purgeAfter": "2020-01-01T00:00:00+00:00"},
    {"retiredAt": "2020-01-01T00:00:00+00:00"},
])
def test_purge_refuses_invalid_dates(world, monkeypatch, capsys, fields):
    job = job_at(world, **fields)
    with pytest.raises(SystemExit):
        command(monkeypatch, "purge")
    assert "invalid retirement dates" in capsys.readouterr().err
    assert job.exists()


def test_purge_boundary_and_restore_after_deadline(world, monkeypatch):
    at = datetime.now(timezone.utc)
    fields = {"retiredAt": (at - timedelta(days=14)).isoformat(), "purgeAfter": at.isoformat()}
    assert not retirement.purge_due(fields, at - timedelta(microseconds=1))
    assert retirement.purge_due(fields, at)
    job = job_at(world, **fields)
    command(monkeypatch, "restore", "owner/job")
    command(monkeypatch, "purge")
    assert job.exists() and not core.load_state(job).get("retiredAt")


def test_locks_prevent_retire_restore_and_purge(world, monkeypatch):
    job = job_at(world)
    fd = core.lock_runner(job)
    try:
        for args in [("retire", "owner/job"), ("restore", "owner/job"), ("purge", "owner/job")]:
            with pytest.raises(SystemExit):
                command(monkeypatch, *args)
        assert not core.load_state(job).get("retiredAt")
        assert not cli.ARCHIVE.exists()
    finally:
        os.close(fd)


def test_immediate_purge_refuses_dirty_worktree(world, monkeypatch, capsys):
    job = job_at(world)
    wt = job / "out/wt"
    wt.mkdir(parents=True)
    (wt / ".git").write_text("gitdir: missing")
    command(monkeypatch, "retire", "owner/job")
    with pytest.raises(SystemExit):
        command(monkeypatch, "retire", "owner/job", "--purge")
    assert "dirty or unreadable" in capsys.readouterr().err
    assert job.exists()


def test_purge_removes_clean_git_worktree_and_preserves_dirty_one(world, monkeypatch, tmp_path, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                    "-c", "commit.gpgsign=false", "commit", "-q", "--allow-empty", "-m", "initial"],
                   check=True)
    for name in ("clean", "dirty"):
        job = job_at(world, f"owner/{name}")
        wt = job / "out/wt"
        subprocess.run(["git", "-C", str(repo), "worktree", "add", "-q", "--detach", str(wt)], check=True)
        if name == "dirty":
            (wt / "keep.txt").write_text("unfinished work")
            with pytest.raises(SystemExit):
                command(monkeypatch, "retire", f"owner/{name}", "--purge")
            assert "dirty or unreadable" in capsys.readouterr().err
            assert (wt / "keep.txt").read_text() == "unfinished work"
        else:
            command(monkeypatch, "retire", f"owner/{name}", "--purge")
            assert not job.exists()
    listed = subprocess.run(["git", "-C", str(repo), "worktree", "list", "--porcelain"],
                            capture_output=True, text=True, check=True).stdout
    assert str(world / "owner/clean/out/wt") not in listed
    assert str(world / "owner/dirty/out/wt") in listed


@pytest.mark.parametrize("link_out", [False, True])
def test_purge_does_not_follow_worktree_symlinks(world, monkeypatch, tmp_path, link_out):
    job = job_at(world)
    external = tmp_path / "external"
    external.mkdir()
    target = external / "wt" if link_out else external
    target.mkdir(exist_ok=True)
    (target / ".git").write_text("gitdir: missing")
    (target / "keep.txt").write_text("external data")
    if link_out:
        (job / "out").symlink_to(external, target_is_directory=True)
    else:
        (job / "out").mkdir()
        (job / "out/wt").symlink_to(external, target_is_directory=True)
    command(monkeypatch, "retire", "owner/job", "--purge")
    assert not job.exists() and (target / "keep.txt").read_text() == "external data"


@pytest.mark.parametrize("days", ["0", "-1", "999999999999999999999999"])
def test_invalid_retention_does_not_retire(world, monkeypatch, days):
    job = job_at(world)
    with pytest.raises(SystemExit):
        command(monkeypatch, "retire", "owner/job", "--keep-days", days)
    assert not core.load_state(job).get("retiredAt")
    assert not cli.ARCHIVE.exists()


def test_expired_job_with_live_runner_is_not_purged(world, monkeypatch, capsys):
    job = job_at(world, retiredAt="2020-01-01T00:00:00+00:00", purgeAfter="2020-01-15T00:00:00+00:00")
    monkeypatch.setattr(watch, "running", lambda _: True)
    with pytest.raises(SystemExit):
        command(monkeypatch, "purge")
    assert "live runner" in capsys.readouterr().err
    assert job.exists()


def test_peer_messages_do_not_target_retired_jobs(world, monkeypatch):
    sender = job_at(world, "owner/sender")
    peer = job_at(world, "owner/peer", retiredAt="2026-01-01T00:00:00+00:00")
    core.route_to_peers(sender, "TO peer: follow up")
    assert not (peer / "steer").exists()
    assert '"kind":"peer_unknown"' in (sender / "live.jsonl").read_text()


@pytest.mark.parametrize("raw", ['[]', '{broken'])
def test_malformed_state_is_not_purged_or_messaged(world, monkeypatch, raw):
    sender = job_at(world, "owner/sender")
    peer = job_at(world, "owner/peer")
    (peer / "state.json").write_text(raw)
    with pytest.raises(SystemExit):
        command(monkeypatch, "purge")
    assert peer.exists()
    core.route_to_peers(sender, "TO peer: follow up")
    assert not (peer / "steer").exists()


@pytest.mark.parametrize("action", ["retire", "restore", "purge"])
def test_workers_cannot_change_retirement(world, monkeypatch, action):
    monkeypatch.setenv(core.WORKER_FLAG, "1")
    with pytest.raises(SystemExit) as error:
        command(monkeypatch, action, "owner/job")
    assert error.value.code == 2

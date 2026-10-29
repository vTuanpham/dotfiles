import json
import os
import signal
import subprocess
import sys
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from agent_lab.cli import actor, main, parser
from agent_lab.files import inspect_tree, lock
from agent_lab.models import Actor, Run, load
from agent_lab.store import Store, default_root, now

ACTOR = Actor("codex", "session-a", "model-a", "high", "/example", None, None, None)


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "state")


def create(store, name="probe"):
    with store.locked():
        return store.create(name, "Compare an experiment", ACTOR)


def test_lifecycle_stable_paths_keep_and_dry_run(store):
    record = create(store)
    base = store.directory(record.id)
    (base / "artifacts/result.txt").write_text("useful output")
    future = now() + timedelta(days=15)
    with store.locked():
        assert store.gc(at=future, apply=True) == []
        retired = store.change(record.id, "retire", summary="finding promoted")
        assert retired.state == "retired"
        assert store.change(record.id, "retire").purge_after == retired.purge_after
        assert store.gc() == []
        assert store.gc(at=future) == [{"id": record.id, "action": "would-purge"}]
        assert (base / "artifacts/result.txt").read_text() == "useful output"
        assert store.change(record.id, "restore").state == "active"
        assert store.directory(record.id) == base
        assert store.change(record.id, "keep").state == "kept"
        with pytest.raises(ValueError, match="kept"):
            store.change(record.id, "retire")
        assert store.gc(at=future, apply=True) == []
        store.change(record.id, "restore")
        store.change(record.id, "retire")
        assert store.gc(at=future, apply=True) == [{"id": record.id, "action": "purged"}]
        assert not base.exists()
        assert store.all() == []


def test_gc_never_follows_symlinks_or_removes_unregistered_data(store, tmp_path):
    record = create(store)
    external = tmp_path / "external"
    external.mkdir()
    (external / "valuable").write_text("keep")
    base = store.directory(record.id)
    (base / "work/link").symlink_to(external, target_is_directory=True)
    unknown = store.workspaces / "unregistered"
    unknown.mkdir()
    with store.locked():
        store.change(record.id, "retire")
        assert store.gc(at=now() + timedelta(days=15), apply=True)[0]["action"] == "purged"
    assert (external / "valuable").read_text() == "keep"
    assert unknown.exists()


@pytest.mark.parametrize("kind", ["git-directory", "git-file", "mount", "root-symlink"])
def test_gc_refuses_git_mounts_and_redirected_roots(store, tmp_path, monkeypatch, kind):
    record = create(store)
    base = store.directory(record.id)
    with store.locked():
        store.change(record.id, "retire")
    if kind == "git-directory":
        (base / "work/.git").mkdir()
    elif kind == "git-file":
        (base / "work/.git").write_text("gitdir: /elsewhere")
    elif kind == "mount":
        monkeypatch.setattr(os.path, "ismount", lambda path: Path(path) == base / "work")
    else:
        moved = tmp_path / "original"
        base.rename(moved)
        base.symlink_to(moved, target_is_directory=True)
    with store.locked():
        assert store.gc(at=now() + timedelta(days=15), apply=True)[0]["action"] == "blocked"
        assert store.read(record.id)
    assert base.exists()


def test_shared_run_and_retirement_lock(store):
    record = create(store)
    with lock(store.locks / record.id):
        with store.locked():
            assert store.running(record.id)
            with pytest.raises(ValueError, match="in use"):
                store.change(record.id, "retire")
        with pytest.raises(ValueError, match="in use"):
            store.run(record.id, [sys.executable, "-c", "pass"], ACTOR)


def test_gc_refuses_an_expired_lab_with_a_live_lease(store):
    record = create(store)
    with store.locked():
        store.change(record.id, "retire")
    with lock(store.locks / record.id), store.locked():
        result = store.gc(at=now() + timedelta(days=15), apply=True)
        assert result[0]["action"] == "blocked"
        assert "in use" in result[0]["reason"]
    assert store.directory(record.id).exists()


def test_run_preserves_argv_exit_cwd_and_separates_creator_from_latest_actor(store):
    record = create(store)
    other = replace(ACTOR, harness="claude", model="model-b", session="session-b")
    command = [
        sys.executable,
        "-c",
        "import os,sys,pathlib; "
        "assert pathlib.Path.cwd().name == 'work'; "
        "assert os.environ['TMPDIR'] == os.environ['AGENT_LAB_TMP']; "
        "pathlib.Path(os.environ['AGENT_LAB_ARTIFACTS'], 'argument').write_text(sys.argv[1]); "
        "sys.exit(17)",
        "literal $(never run) ; & spaces",
    ]
    assert store.run(record.id, command, other) == 17
    with store.locked():
        saved = store.read(record.id)
    assert saved.created_by == ACTOR
    assert saved.last_run.actor == other
    assert saved.last_run.exit_code == 17
    assert saved.last_run.finished_at is not None
    assert (store.directory(record.id) / "artifacts/argument").read_text() == command[-1]


def test_launch_failure_recorded_and_retired_run_rejected(store):
    record = create(store)
    with pytest.raises(FileNotFoundError):
        store.run(record.id, ["/no/such/executable"], ACTOR)
    with store.locked():
        assert store.read(record.id).last_run.exit_code == 127
        store.change(record.id, "retire")
    with pytest.raises(ValueError, match="restore"):
        store.run(record.id, [sys.executable, "-c", "pass"], ACTOR)


def test_cli_streams_stdin_stdout_and_run_leases_across_processes(store):
    env = {
        **os.environ,
        "XDG_STATE_HOME": str(store.root.parent),
        "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
    }
    # Match Store's production root name while keeping every test outside real user state.
    env["XDG_STATE_HOME"] = str(store.root.parent / "cli")
    cli_store = Store(Path(env["XDG_STATE_HOME"]) / "agent-lab")
    cli_record = create(cli_store)
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "agent_lab.cli",
            "run",
            cli_record.id,
            "--model",
            "worker",
            "--",
            sys.executable,
            "-c",
            "import sys; print('ready', flush=True); print(sys.stdin.readline().strip())",
        ],
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdout.readline().strip() == "ready"
        with cli_store.locked():
            assert cli_store.running(cli_record.id)
            with pytest.raises(ValueError, match="in use"):
                cli_store.change(cli_record.id, "retire")
        out, err = proc.communicate("hello\n", timeout=10)
        assert proc.returncode == 0, err
        assert out.strip() == "hello"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate(timeout=10)


def test_direct_child_keeps_lease_after_wrapper_crash(store):
    env = {
        **os.environ,
        "XDG_STATE_HOME": str(store.root.parent),
        "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
    }
    env["XDG_STATE_HOME"] = str(store.root.parent / "crash")
    child_store = Store(Path(env["XDG_STATE_HOME"]) / "agent-lab")
    child_record = create(child_store)
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "agent_lab.cli",
            "run",
            child_record.id,
            "--",
            sys.executable,
            "-c",
            "import os,sys; print(os.getpid(), flush=True); sys.stdin.read()",
        ],
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    child = None
    try:
        child = int(proc.stdout.readline().strip())
        proc.kill()
        proc.wait(timeout=10)
        with child_store.locked():
            assert child_store.running(child_record.id)
            with pytest.raises(ValueError, match="in use"):
                child_store.change(child_record.id, "retire")
    finally:
        if child is not None:
            os.kill(child, signal.SIGTERM)
        if proc.poll() is None:
            proc.kill()
        proc.communicate(timeout=10)


@pytest.mark.parametrize(
    "damage",
    [
        "duplicate",
        "schema",
        "naive-time",
        "bad-actor",
        "boolean-exit",
        "retirement",
        "nan",
        "extra",
        "mismatched-id",
    ],
)
def test_registry_rejects_corruption_before_gc(store, damage):
    record = create(store)
    data = record.to_dict()
    if damage == "schema":
        data["schema"] = True
    elif damage == "naive-time":
        data["created_at"] = "2026-01-01T00:00:00"
    elif damage == "bad-actor":
        data["created_by"]["cwd"] = "relative"
    elif damage == "boolean-exit":
        data["last_run"] = {
            "actor": ACTOR.__dict__,
            "started_at": record.created_at,
            "finished_at": record.updated_at,
            "exit_code": True,
        }
    elif damage == "retirement":
        data["retired_at"] = record.created_at
    elif damage == "nan":
        data["purpose"] = float("nan")
    elif damage == "extra":
        data["guess"] = "unknown"
    elif damage == "mismatched-id":
        data["id"] = "other-000000000000"
    raw = json.dumps(data)
    if damage == "duplicate":
        raw = raw.replace('"schema": 1', '"schema": 1, "schema": 1')
    target = store.records / f"{record.id}.json"
    target.write_text(raw)
    with store.locked(), pytest.raises(ValueError):
        store.gc(at=now() + timedelta(days=15), apply=True)
    assert store.directory(record.id).exists()


def test_private_registry_file_and_directory_permissions(store, tmp_path):
    record = create(store)
    target = store.records / f"{record.id}.json"
    assert target.stat().st_mode & 0o777 == 0o600
    assert store.root.stat().st_mode & 0o777 == 0o700
    target.chmod(0o644)
    with pytest.raises(ValueError, match="owner-only"):
        store.read(record.id)
    target.unlink()
    target.symlink_to(tmp_path / "missing")
    with pytest.raises(OSError):
        store.read(record.id)


def test_size_warnings_use_logical_size_and_skip_link_targets(store, tmp_path):
    record = create(store)
    base = store.directory(record.id)
    large = base / "artifacts/large.bin"
    with large.open("wb") as file:
        file.truncate(1024**3)
    external = tmp_path / "outside"
    external.mkdir()
    (external / "extra").write_text("not counted")
    (base / "work/external").symlink_to(external, target_is_directory=True)
    result = inspect_tree(base)
    assert result["bytes"] == 1024**3
    assert result["files"] == 1
    assert len(result["warnings"]) == 2
    assert result["largest_path"] == "artifacts/large.bin"


def test_default_root_and_known_provenance_only(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", "relative")
    assert default_root() == Path.home() / ".local/state/agent-lab"
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_THREAD_ID", "origin-session")
    monkeypatch.delenv("AGENT_LAB_HARNESS", raising=False)
    monkeypatch.delenv("AGENT_LAB_SESSION", raising=False)
    monkeypatch.delenv("AGENT_LAB_MODEL", raising=False)
    monkeypatch.delenv("AGENT_LAB_EFFORT", raising=False)
    args = parser().parse_args(["new", "probe", "--purpose", "verify"])
    result = actor(args)
    assert result.harness == "codex"
    assert result.session == "origin-session"
    assert result.model is None
    assert default_root() == tmp_path / "agent-lab"


def test_cli_json_paths_and_invalid_ids(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert main(["new", "check", "--purpose", "test", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert set(data["paths"]) == {"root", "work", "tmp", "artifacts"}
    assert main(["path", data["id"], "--area", "artifacts"]) == 0
    assert capsys.readouterr().out.strip() == data["paths"]["artifacts"]
    assert main(["path", "../../elsewhere"]) == 1
    capsys.readouterr()
    assert main(["show", data["id"]]) == 0
    assert json.loads(capsys.readouterr().out)["size"]["bytes"] == 0
    assert main(["list", "--json"]) == 0
    assert len(json.loads(capsys.readouterr().out)) == 1


def test_boundary_validates_record_size_and_text(store):
    with store.locked():
        with pytest.raises(ValueError):
            store.create("escape/name", "reason", ACTOR)
        with pytest.raises(ValueError):
            store.create("fine", "", ACTOR)
    record = create(store)
    target = store.records / f"{record.id}.json"
    target.write_text(" " * 65537)
    with pytest.raises(ValueError, match="too large"):
        store.read(record.id)
    with pytest.raises(ValueError):
        load('{"schema": Infinity}')


def test_oversized_writes_leave_the_previous_record_readable(store):
    record = create(store)
    huge_actor = replace(ACTOR, cwd="/" + "中" * 4000, repository="/" + "中" * 4000)
    oversized = replace(
        record,
        created_by=huge_actor,
        purpose="中" * 2000,
        summary="中" * 4000,
        last_run=Run(huge_actor, record.created_at, record.updated_at, 0),
    )
    with store.locked():
        with pytest.raises(ValueError, match="too large"):
            store.save(oversized)
        assert store.read(record.id) == record


def test_read_commands_use_no_write_descriptors_or_new_lock_files(store, monkeypatch, capsys):
    record = create(store)
    monkeypatch.setenv("AGENT_LAB_HOME", str(store.root))
    original_open = os.open
    before = set(store.locks.iterdir())

    def readonly_open(path, flags, *args, **kwargs):
        assert not flags & (os.O_RDWR | os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
        return original_open(path, flags, *args, **kwargs)

    with monkeypatch.context() as restricted:
        restricted.setattr(os, "open", readonly_open)
        assert main(["show", record.id]) == 0
        assert json.loads(capsys.readouterr().out)["running"] is False
        assert main(["list", "--json"]) == 0
        assert len(json.loads(capsys.readouterr().out)) == 1
        assert main(["path", record.id]) == 0
        capsys.readouterr()
    assert set(store.locks.iterdir()) == before
    with lock(store.locks / record.id):
        with store.locked(read_only=True):
            assert store.running(record.id)


def test_empty_read_only_list_does_not_initialize_state(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AGENT_LAB_HOME", str(tmp_path / "missing"))
    assert main(["list", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == []
    assert not (tmp_path / "missing").exists()
    monkeypatch.setenv("AGENT_LAB_HOME", "relative")
    assert main(["list", "--json"]) == 1
    assert "must be absolute" in capsys.readouterr().err


def test_nested_tools_keep_the_registry_when_native_profiles_change_home(store, tmp_path):
    record = create(store)
    command = [
        sys.executable,
        "-c",
        "import os; from agent_lab.store import Store; "
        "os.environ['HOME'] = os.environ['AGENT_LAB_TMP']; "
        "os.environ['XDG_STATE_HOME'] = os.environ['AGENT_LAB_TMP']; "
        "s=Store(); assert s.read(os.environ['AGENT_LAB_ID']).purpose == 'Compare an experiment'",
    ]
    assert store.run(record.id, command, ACTOR) == 0


@pytest.mark.parametrize("harness", ["codex", "claude", "agy", "opencode"])
def test_core_lifecycle_has_no_harness_or_language_dependency(harness, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AGENT_LAB_HOME", str(tmp_path / harness))
    monkeypatch.setenv("AGENT_LAB_HARNESS", harness)
    assert main(["new", "probe", "--purpose", "Check cross-harness CLI", "--json"]) == 0
    record = json.loads(capsys.readouterr().out)
    assert record["created_by"]["harness"] == harness
    identifier = record["id"]
    assert main(["run", identifier, "--", "/usr/bin/true"]) == 0
    capsys.readouterr()
    assert main(["retire", identifier]) == 0
    capsys.readouterr()
    assert main(["gc"]) == 0
    assert json.loads(capsys.readouterr().out) == []
    assert main(["restore", identifier]) == 0
    capsys.readouterr()

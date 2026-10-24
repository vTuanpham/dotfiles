import io
import json
import threading

from agent_bridge.cli import read_prompt
from agent_bridge.core import (
    confirm_steer,
    lock_runner,
    make_steer,
    poll_steers,
    resolve_job,
    route_to_peers,
    runner_finished,
)


def test_job_resolution(monkeypatch, tmp_path):
    monkeypatch.setattr("agent_bridge.core.JOBS", tmp_path)
    assert resolve_job("owner/job") == (tmp_path / "owner/job").resolve()
    for value in ("job", "a/b/c", "../a/b"):
        try:
            resolve_job(value)
        except ValueError:
            pass
        else:
            raise AssertionError(value)
    outside = tmp_path.parent / "outside"
    outside.mkdir()
    (tmp_path / "owner").symlink_to(outside, target_is_directory=True)
    try:
        resolve_job("owner/job")
    except ValueError:
        pass
    else:
        raise AssertionError("symlink escaped jobs root")


def test_steer_numbering(tmp_path):
    assert make_steer(tmp_path, "one").name == "001.md"
    (tmp_path / "steer/sent").mkdir()
    (tmp_path / "steer/sent/001.md").write_text("one")
    assert make_steer(tmp_path, "two").name == "002.md"


def test_concurrent_steers_keep_all_messages(tmp_path):
    paths = []
    threads = [
        threading.Thread(target=lambda n=n: paths.append(make_steer(tmp_path, str(n)))) for n in range(12)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len({p.name for p in paths}) == 12
    assert len(list((tmp_path / "steer").glob("[0-9]*.md"))) == 12


def test_codex_steer_persists_inflight_and_uses_stable_client_id(tmp_path):
    (tmp_path / "state.json").write_text(json.dumps({"inflight": None}))
    make_steer(tmp_path, "deliver once")
    sent = []

    def send(text, cid):
        sent.append((text, cid, json.loads((tmp_path / "state.json").read_text())["inflight"]))

    state = {"inflight": None}
    assert poll_steers(tmp_path, send, state=state)
    assert sent == [("deliver once", "steer-001", {"id": "steer-001", "file": "001.md"})]
    assert state["inflight"] is None
    assert (tmp_path / "steer/sent/001.md").is_file()


def test_deferred_steer_stays_queued_until_confirmed_and_redelivers(tmp_path):
    (tmp_path / "state.json").write_text(json.dumps({"inflight": None}))
    make_steer(tmp_path, "deliver reliably")
    state = {"inflight": None}
    sent = []

    def send(text):
        sent.append((text, json.loads((tmp_path / "state.json").read_text())["inflight"]))

    assert poll_steers(tmp_path, send, state=state, defer=True)
    assert sent == [("deliver reliably", {"id": "steer-001", "file": "001.md"})]
    assert (tmp_path / "steer/001.md").is_file()
    assert not (tmp_path / "steer/sent/001.md").exists()

    state = json.loads((tmp_path / "state.json").read_text())
    assert poll_steers(tmp_path, send, state=state, defer=True, redeliver=True)
    assert sent[-1][0] == (
        "(redelivered after a runner restart; skip it if you already handled it)\ndeliver reliably"
    )
    assert json.loads((tmp_path / "state.json").read_text())["inflight"] == state["inflight"]
    confirm_steer(tmp_path, state)
    assert state["inflight"] is None
    assert (tmp_path / "steer/sent/001.md").is_file()
    assert any(
        json.loads(line)["kind"] == "steer_redelivered"
        for line in (tmp_path / "live.jsonl").read_text().splitlines()
    )


def test_peer_routing_rejects_path_segments(tmp_path):
    job = tmp_path / "owner" / "worker"
    victim = tmp_path / "victim"
    job.mkdir(parents=True)
    victim.mkdir()
    (victim / "state.json").write_text("{}")
    route_to_peers(job, "TO ../victim: steal")
    assert not (victim / "steer").exists()


def test_peer_routing_treats_coordinator_addresses_as_plain_messages(tmp_path):
    job = tmp_path / "owner" / "worker"
    job.mkdir(parents=True)
    route_to_peers(job, "TO root, coordinator, owner: checkpoint")
    log = job / "live.jsonl"
    assert not log.exists() or "peer_unknown" not in log.read_text()
    route_to_peers(job, "TO missing: hello")
    assert "peer_unknown" in log.read_text()


def test_runner_finished_preserves_another_runner_pid(tmp_path, monkeypatch):
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"runnerPid": 123, "activeTurnId": "turn"}))
    monkeypatch.setattr("agent_bridge.core.os.getpid", lambda: 456)
    runner_finished({}, state_path)
    assert json.loads(state_path.read_text()) == {"runnerPid": 123, "activeTurnId": "turn"}


def test_runner_lock_rejects_a_second_owner(tmp_path):
    fd = lock_runner(tmp_path)
    try:
        try:
            lock_runner(tmp_path)
        except RuntimeError as exc:
            assert str(exc) == "job already has a runner"
        else:
            raise AssertionError("second runner acquired lock")
    finally:
        import os

        os.close(fd)


def test_read_prompt(monkeypatch, tmp_path):
    source = tmp_path / "prompt.md"
    source.write_text("from file\n")
    assert read_prompt(source) == "from file"
    monkeypatch.setattr("sys.stdin", io.StringIO("from stdin"))
    assert read_prompt("-") == "from stdin"
    (tmp_path / "empty.md").write_text("  \n")
    try:
        read_prompt(tmp_path / "empty.md")
    except RuntimeError:
        pass
    else:
        raise AssertionError("empty prompt accepted")

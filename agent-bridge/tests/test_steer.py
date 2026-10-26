import multiprocessing
import os
import sys
import time

import pytest

from agent_bridge import cli, core


@pytest.fixture
def job(tmp_path, monkeypatch):
    job = tmp_path / "owner/job"
    job.mkdir(parents=True)
    core.save(job / "state.json", {"backend": "codex", "threadId": "original", "autoAnswers": 2})
    monkeypatch.delenv(core.WORKER_FLAG, raising=False)
    monkeypatch.setattr(cli, "resolve_job", lambda _: job)
    monkeypatch.setattr(cli, "linger", lambda *args: None)
    monkeypatch.setattr(cli.agy, "fallback", lambda *args: None)
    return job


def steer(text="follow up", *flags):
    argv = sys.argv
    sys.argv = ["agent-bridge", "steer", "owner/job", text, *flags]
    try:
        cli.main()
    finally:
        sys.argv = argv


def steer_argv(*args):
    argv = sys.argv
    sys.argv = ["agent-bridge", "steer", *args]
    try:
        cli.main()
    finally:
        sys.argv = argv


def deliver(job, state, path, prompt, resume=False):
    core.runner_started(state, path)
    core.log(job, "test_run", prompt=prompt, resume=resume, pid=os.getpid())
    while core.poll_steers(
        job, lambda text, cid: core.log(job, "test_delivery", text=text, cid=cid), state=state
    ):
        pass
    core.log(job, "turn_completed")
    core.runner_finished(state, path)


def wait_idle(job):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            fd = core.lock_runner(job)
        except RuntimeError:
            time.sleep(0.01)
        else:
            os.close(fd)
            for event in cli.events(job):
                if event["kind"] == "test_run":
                    try:
                        os.waitpid(event["pid"], 0)
                    except ChildProcessError:
                        pass
            return
    pytest.fail("runner did not finish")


@pytest.mark.parametrize("args,timeout,text", [
    (("owner/job", "--watch", "after flag"), 1800, "after flag"),
    (("owner/job", "--watch", "20", "after timeout"), 20, "after timeout"),
    (("owner/job", "--watch=20", "after equals"), 20, "after equals"),
    (("owner/job", "before flag", "--watch"), 1800, "before flag"),
    (("owner/job", "123", "--watch"), 1800, "123"),
])
def test_steer_watch_positionals(job, monkeypatch, args, timeout, text):
    monkeypatch.setattr(cli.codex, "run", deliver)
    seen = []
    monkeypatch.setattr(cli, "watch", lambda *args, **kwargs: seen.append(kwargs) or True)
    steer_argv(*args)
    wait_idle(job)
    assert (job / "steer/sent/001.md").read_text() == text + "\n"
    assert seen[0]["timeout"] == timeout


def test_invalid_watch_with_existing_text_errors_helpfully(job, monkeypatch, capsys):
    with pytest.raises(SystemExit) as error:
        steer_argv("owner/job", "first message", "--watch", "a long invalid watch value")
    message = capsys.readouterr().err
    assert error.value.code == 2
    assert "put text before --watch" in message
    assert "use --watch=SECONDS" in message
    assert "or use --prompt-file" in message
    assert "a long invalid watch value" not in message
    assert not (job / "steer").exists()


@pytest.mark.parametrize("backend,key", [
    ("codex", "threadId"), ("claude", "sessionId"),
    ("agy", "conversationId"), ("opencode", "sessionId"),
])
def test_idle_steer_resumes_detached_and_delivers(job, monkeypatch, capfd, backend, key):
    core.save(job / "state.json", {"backend": backend, key: "original", "activeTurnId": None})
    monkeypatch.setattr(cli.BACKENDS[backend], "run", deliver)
    steer()
    wait_idle(job)
    assert capfd.readouterr().out.splitlines() == [
        "delivered by resuming the idle job; watch: agent-bridge watch owner/job"
    ]
    runs = [e for e in cli.events(job) if e["kind"] == "test_run"]
    assert len(runs) == 1 and runs[0]["resume"] and runs[0]["prompt"] == ""
    assert runs[0]["pid"] != os.getpid()
    assert (job / "steer/sent/001.md").read_text() == "follow up\n"
    state = core.load_state(job)
    assert state[key] == "original" and state["autoAnswers"] == 0


def test_idle_steer_watch_reads_from_before_enqueue(job, monkeypatch, capfd):
    core.log(job, "old")
    before = (job / "live.jsonl").stat().st_size
    monkeypatch.setattr(cli.codex, "run", deliver)
    seen = []
    monkeypatch.setattr(cli, "watch", lambda *args, **kwargs: seen.append((args, kwargs)) or True)
    steer("follow up", "--watch", "20")
    wait_idle(job)
    assert seen == [((["owner/job"], True), {"timeout": 20, "offsets": {job: before}})]


def test_concurrent_steers_share_one_resume_and_deliver_in_queue_order(job, monkeypatch, capfd):
    ctx = multiprocessing.get_context("fork")
    release = ctx.Event()

    def run(*args, **kwargs):
        core.runner_started(args[1], args[2])
        assert release.wait(5)
        deliver(*args, **kwargs)

    monkeypatch.setattr(cli.codex, "run", run)
    done = [ctx.Event(), ctx.Event()]

    def command(text, returned):
        steer(text)
        returned.set()

    workers = [ctx.Process(target=command, args=(text, returned))
               for text, returned in zip(("first", "second"), done)]
    try:
        for worker in workers:
            worker.start()
        for returned in done:
            assert returned.wait(5)
    finally:
        release.set()
        for worker in workers:
            worker.join(5)
            if worker.is_alive():
                worker.terminate()
                worker.join()
    assert all(worker.exitcode == 0 for worker in workers)
    wait_idle(job)
    events = cli.events(job)
    assert len([e for e in events if e["kind"] == "test_run"]) == 1
    deliveries = [e for e in events if e["kind"] == "test_delivery"]
    assert [e["cid"] for e in deliveries] == ["steer-001", "steer-002"]
    assert {e["text"] for e in deliveries} == {"first", "second"}
    assert [e["text"] for e in deliveries] == [
        p.read_text().strip() for p in sorted((job / "steer/sent").glob("*.md"))
    ]
    assert capfd.readouterr().out.count("delivered by resuming") == 1


def test_steer_while_runner_finishes_is_delivered_by_that_runner(job, monkeypatch):
    ctx = multiprocessing.get_context("fork")
    ready, finish, finished = ctx.Event(), ctx.Event(), ctx.Event()

    def run(job, state, path, prompt, resume=False):
        if resume:
            return deliver(job, state, path, prompt, resume)
        core.runner_started(state, path)
        core.runner_finished(state, path)  # backend cleanup precedes runner lock release
        ready.set()
        assert finish.wait(5)
        finished.set()

    def start():
        fd = core.lock_runner(job)
        cli.run_with_linger(job, core.load_state(job), job / "state.json", cli.codex, "work", False, {}, fd)

    make_steer = cli.make_steer

    def enqueue(*args):
        finish.set()
        assert finished.wait(5)
        return make_steer(*args)

    monkeypatch.setattr(cli.codex, "run", run)
    worker = ctx.Process(target=start)
    worker.start()
    try:
        assert ready.wait(5)
        monkeypatch.setattr(cli, "make_steer", enqueue)
        monkeypatch.setattr(cli.os, "fork", lambda: pytest.fail("existing runner must own delivery"))
        steer()
        worker.join(5)
        assert worker.exitcode == 0
        assert (job / "steer/sent/001.md").read_text() == "follow up\n"
        runs = [e for e in cli.events(job) if e["kind"] == "test_run"]
        assert len(runs) == 1 and runs[0]["resume"]
    finally:
        finish.set()
        if worker.is_alive():
            worker.terminate()
            worker.join()


@pytest.mark.parametrize("active,question", [(True, False), (False, False), (True, True)])
def test_live_runner_steer_preserves_turn_and_question(job, monkeypatch, active, question):
    state = core.load_state(job)
    state.update(activeTurnId="turn" if active else None, runnerPid=os.getpid())
    core.save(job / "state.json", state)
    original = (job / "state.json").read_bytes()
    if question:
        core.log(job, "question", requestId="pending")
    fd = core.lock_runner(job)
    monkeypatch.setattr(cli.os, "fork", lambda: pytest.fail("live runner must not be duplicated"))
    try:
        steer()
    finally:
        os.close(fd)
    assert (job / "state.json").read_bytes() == original
    assert (job / "steer/001.md").read_text() == "follow up\n"
    assert not (job / "inbox").exists()


def test_steer_retired_job_requires_restore(job, capsys):
    state = core.load_state(job)
    state["retiredAt"] = core.stamp()
    core.save(job / "state.json", state)
    with pytest.raises(SystemExit) as error:
        steer()
    assert error.value.code == 1
    assert "agent-bridge restore owner/job" in capsys.readouterr().err
    assert not (job / "steer").exists()
    assert core.load_state(job) == state


def test_runner_resets_auto_answers_after_delivering_root_steer(job, monkeypatch):
    def run(job, state, path, prompt, resume=False):
        steer()
        deliver(job, state, path, prompt, resume)

    def linger(job, state, *args):
        assert state["autoAnswers"] == 0

    monkeypatch.setattr(cli.codex, "run", run)
    monkeypatch.setattr(cli, "linger", linger)
    cli.run_with_linger(job, core.load_state(job), job / "state.json", cli.codex, "work", False, {},
                        core.lock_runner(job))
    assert core.load_state(job)["autoAnswers"] == 0


@pytest.mark.parametrize("flags", [("--queue", "--watch"), ()])
def test_invalid_steer_does_not_queue(job, flags):
    with pytest.raises(SystemExit):
        steer("" if not flags else "follow up", *flags)
    assert not (job / "steer").exists()


@pytest.mark.parametrize("ending", ["stopped", "compact", "error"])
def test_runner_leaves_queue_on_stop_compact_or_error(job, ending):
    core.make_steer(job, "later")
    calls = []

    class Backend:
        def run(self, job, state, path, prompt, **kwargs):
            calls.append(kwargs)
            if ending == "error":
                raise RuntimeError("backend failed")
            core.log(job, ending)

    fd = core.lock_runner(job)
    extra = {"compact": True} if ending == "compact" else {}
    if ending == "error":
        with pytest.raises(RuntimeError, match="backend failed"):
            cli.run_with_linger(job, core.load_state(job), job / "state.json", Backend(), "", True, extra, fd)
    else:
        cli.run_with_linger(job, core.load_state(job), job / "state.json", Backend(), "", True, extra, fd)
    assert len(calls) == 1
    assert (job / "steer/001.md").read_text() == "later\n"
    os.close(core.lock_runner(job))

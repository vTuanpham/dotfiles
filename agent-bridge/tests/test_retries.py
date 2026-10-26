import pytest

from agent_bridge import cli, core, retries
from agent_bridge.acknowledgements import pending, urgent


@pytest.mark.parametrize("error", ["server capacity", "model is at capacity", "HTTP 503",
                                  "429 Too Many Requests", "server_error", "rate_limit_exceeded",
                                  {"type": "overloaded_error"}, {"error": {"code": "rate_limit_error"}}])
def test_transient_failures_are_retryable(error):
    assert retries.retryable(error)


@pytest.mark.parametrize("error", ["invalid API key", "permission denied", "model_not_found",
                                  "HTTP 429 insufficient_quota", "billing error 503", "daily quota exceeded",
                                  "context_length_exceeded", "unknown failure", "No space left on device"])
def test_permanent_or_unknown_failures_are_not_retried(error):
    assert not retries.retryable(error)


@pytest.mark.parametrize("upper", [False, True])
def test_backoff_has_bounded_exponential_growth_and_jitter(monkeypatch, upper):
    monkeypatch.setattr(retries.random, "uniform", lambda low, high: high if upper else low)
    expected = [30, 60, 120, 120] if upper else [15, 30, 60, 60]
    assert [retries.delay(n) for n in range(1, 5)] == expected
    assert 165 <= sum(expected) <= 330


@pytest.fixture
def job(tmp_path, monkeypatch):
    job = tmp_path / "owner/job"
    job.mkdir(parents=True)
    (job / "steer").mkdir()
    state = {"backend": "codex", "threadId": "original", "model": "same-model"}
    path = job / "state.json"
    core.save(path, state)
    monkeypatch.setattr(retries, "delay", lambda _: 0)
    return job, state, path


def test_retries_continue_same_session_and_model_without_early_wake(job):
    job, state, path = job
    calls = []

    class Backend:
        def run(self, job, state, path, prompt, resume=False):
            calls.append((prompt, resume, state["model"], state["threadId"]))
            if len(calls) == 1:
                core.log(job, "turn_completed", status="failed", error="server capacity")
            else:
                core.log(job, "turn_completed", status="completed")

    assert retries.run(job, state, path, Backend(), "work", False, {}) is True
    assert calls == [("work", False, "same-model", "original"),
                     ("Continue.", True, "same-model", "original")]
    events = cli.events(job)
    assert [event["kind"] for event in events] == ["attempt_failed", "retry_wait", "turn_completed"]
    assert all(not urgent(event, include_info=True) for event in events[:-1])
    assert [event["kind"] for _, event in pending(job)] == ["turn_completed"]
    assert "retry" not in core.load_state(job)


def test_exception_retries_and_exhaustion_produces_one_actionable_failure(job):
    job, state, path = job
    calls = []

    class Backend:
        def run(self, job, state, path, prompt, resume=False):
            calls.append(prompt)
            core.log(job, "error", message="503 server overloaded")
            raise RuntimeError("503 server overloaded")

    assert retries.run(job, state, path, Backend(), "work", False, {}) is False
    assert calls == ["work", "Continue.", "Continue.", "Continue.", "Continue."]
    events = cli.events(job)
    assert sum(event["kind"] == "retry_wait" for event in events) == 4
    wake = [event for _, event in pending(job)]
    assert len(wake) == 1 and wake[0]["kind"] == "turn_failed"
    assert wake[0]["retries"] == 4 and "retried 4 times" in wake[0]["message"]
    assert "SAME native session" in wake[0]["message"]
    assert "agent-bridge resume owner/job --model M" in wake[0]["message"]


def test_non_retryable_failure_is_not_replayed(job):
    job, state, path = job
    calls = []

    class Backend:
        def run(self, job, state, path, prompt, resume=False):
            calls.append(prompt)
            core.log(job, "turn_completed", status="failed", error="permission denied")

    assert retries.run(job, state, path, Backend(), "work", False, {}) is False
    assert calls == ["work"]
    assert [event["kind"] for _, event in pending(job)] == ["turn_completed"]


def test_queued_steer_takes_precedence_over_retry_continue(job):
    job, state, path = job
    calls = []

    class Backend:
        def run(self, job, state, path, prompt, resume=False):
            calls.append(prompt)
            if len(calls) == 1:
                (job / "steer/001.md").write_text("steer")
                core.log(job, "turn_completed", status="failed", error="server capacity")
            else:
                core.log(job, "turn_completed")

    assert retries.run(job, state, path, Backend(), "work", False, {})
    assert calls == ["work", ""]


def test_retry_does_not_invent_a_missing_native_session(job):
    job, state, path = job
    state.pop("threadId")
    core.save(path, state)

    class Backend:
        def run(self, job, state, path, prompt, resume=False):
            core.log(job, "error", message="server capacity")

    assert retries.run(job, state, path, Backend(), "work", False, {}) is False
    wake = [event for _, event in pending(job)]
    assert len(wake) == 1 and "No native session was recorded" in wake[0]["message"]


def test_native_transient_error_wins_over_generic_process_exit_exception(job):
    job, state, path = job
    calls = []

    class Backend:
        def run(self, job, state, path, prompt, resume=False):
            calls.append(prompt)
            if len(calls) == 1:
                core.log(job, "error", error={"type": "overloaded_error"})
                core.log(job, "error", message="process exited with code 1")
                raise RuntimeError("process exited with code 1")
            core.log(job, "turn_completed")

    assert retries.run(job, state, path, Backend(), "work", False, {})
    assert calls == ["work", "Continue."]
    assert [event["kind"] for _, event in pending(job)] == ["turn_completed"]


def test_stop_cancels_backoff_without_another_backend_call(job, monkeypatch):
    job, state, path = job
    monkeypatch.setattr(retries, "delay", lambda _: 30)
    (job / "stop").touch()
    calls = []

    class Backend:
        def run(self, job, state, path, prompt, resume=False):
            calls.append(prompt)
            core.log(job, "error", message="server capacity")

    assert retries.run(job, state, path, Backend(), "work", False, {}) is False
    assert calls == ["work"] and not (job / "stop").exists()
    assert "retry" not in core.load_state(job)

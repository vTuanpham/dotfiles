"""Retry only transient backend failures, in the existing native session and model."""

import json
import random
import re
import time
from contextvars import ContextVar

ATTEMPT = ContextVar("bridge_retry_attempt", default=None)
MAX_RETRIES = 4


def failed(event):
    status = str(event.get("status", "")).lower()
    return (event.get("kind") in {"error", "turn_failed"}
            or event.get("kind") == "turn_completed"
            and (bool(event.get("error")) or status == "failed" or status.startswith("error")))


def retryable(error):
    text = json.dumps(error, ensure_ascii=False) if isinstance(error, (dict, list)) else str(error)
    if re.search(r"insufficient[_ -]?quota|billing|usage limit|daily quota|quota (?:reached|exceeded)|"
                 r"invalid[_ -]?(?:api[_ -]?)?key|unauthorized|authentication|permission denied|"
                 r"context[_ -]?(?:length|window)|model.*(?:not[_ -]?found|does not exist)", text, re.I):
        return False
    return bool(re.search(r"\boverloaded(?:[_ -]?error)?\b|\bat capacity\b|"
                          r"\bserver[_ -]?(?:capacity|overload|error|unavailable)\b|"
                          r"\brate[_ -]?limit(?:ed|[_ -]?(?:error|exceeded))?\b|"
                          r"\btoo many requests\b|\b(?:429|502|503|504)\b", text, re.I))


def delay(attempt):
    ceiling = min(120, 30 * 2 ** (attempt - 1))
    return random.uniform(ceiling / 2, ceiling)


def run(job, state, path, backend, prompt, resume, extra, *, root_prompt=False):
    from .core import POLL, load_state, log, runner_started, save, stamp

    for count in range(MAX_RETRIES + 1):
        attempt_prompt = prompt
        attempt_started = stamp()
        recorded = []
        token = ATTEMPT.set(recorded)
        error = None
        try:
            backend.run(job, state, path, prompt, resume=resume, **extra)
        except Exception as exc:
            error = exc
        finally:
            ATTEMPT.reset(token)
        failure = next((event for event in recorded if failed(event)), None)
        if error is None and recorded and not failed(recorded[-1]):
            failure = None
        reason = (failure.get("error") or failure.get("message") or failure) if failure else error
        if reason is None:
            if root_prompt and attempt_prompt.strip() and any(
                event.get("kind") == "turn_completed" and not failed(event) for event in recorded
            ):
                from .peers import message_fields

                log(
                    job,
                    "root_prompt",
                    level="info",
                    at=attempt_started,
                    recorded_at=stamp(),
                    **message_fields(attempt_prompt),
                )
            if state.pop("retry", None) is not None:
                save(path, state)
            return True
        if not retryable(reason) or extra.get("compact"):
            if failure:
                log(job, failure["kind"], level="urgent",
                    **{key: value for key, value in failure.items() if key not in {"at", "kind", "level"}})
            elif error is not None:
                log(job, "error", message=str(error))
            if error is not None:
                raise error
            return False
        current = load_state(job)
        state.update(current)
        session_key = {"codex": "threadId", "claude": "sessionId", "agy": "conversationId",
                       "opencode": "sessionId"}.get(state.get("backend"))
        if count == MAX_RETRIES or not session_key or not state.get(session_key):
            state.pop("retry", None)
            save(path, state)
            name = f"{job.parent.name}/{job.name}"
            action = (f"Continue the SAME native session with agent-bridge resume {name} --model M; "
                      "do not start a new job." if session_key and state.get(session_key)
                      else "No native session was recorded; inspect backend setup before continuing.")
            log(job, "turn_failed", level="urgent", retries=count, status="failed",
                message=f"Backend failure; retried {count} times. {action}")
            return False
        seconds = delay(count + 1)
        state["retry"] = {"attempt": count + 1, "maximum": MAX_RETRIES, "delaySeconds": round(seconds, 1)}
        runner_started(state, path)
        log(job, "retry_wait", level="info", **state["retry"],
            message=f"retry {count + 1}/{MAX_RETRIES} in {seconds:.0f}s; same session and model")
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            marker = next((job / name for name in ("stop", "interrupt") if (job / name).exists()), None)
            if marker:
                marker.unlink(missing_ok=True)
                state.pop("retry", None)
                save(path, state)
                log(job, "stopped", level="info")
                return False
            time.sleep(min(POLL, max(0, deadline - time.monotonic())))
        state.pop("retry", None)
        save(path, state)
        prompt = "" if list((job / "steer").glob("[0-9]*.md")) else "Continue."
        root_prompt = False
        resume = True

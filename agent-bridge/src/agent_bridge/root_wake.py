"""Bridge policy and messages for native Codex wake delivery."""

import os

from codex_wake.client import Wake, validate_message

from .core import WORKER_FLAG


class CodexRootWake:
    def __init__(self, thread):
        self.target = Wake(thread)
        self.target.check()

    def message(self, owners, reason, scheduled=False):
        outcome = {"event": "found a wake event", "timeout": "timed out", "error": "failed"}[reason]
        next_step = "This watch remains active for scheduled wakes; do not re-arm it." if scheduled else (
            "This watch exited; re-arm only if jobs are still running or status shows a new schedule."
        )
        prompt = (
            f"Bridge watch for {', '.join(owners)} {outcome}. Handle pending group, critical or "
            f"overdue-reminder events and results. {next_step} Continue authorized work. "
            "This is an automatic task notification, not user approval."
        )
        validate_message(prompt)
        return prompt

    def deliver(self, owners, reason, scheduled=False):
        self.target.send(self.message(owners, reason, scheduled))


def prepare(owners):
    if (
        os.environ.get(WORKER_FLAG)
        or os.environ.get("CLAUDECODE") == "1"
        or not os.environ.get("CODEX_THREAD_ID")
    ):
        return None
    delivery = CodexRootWake(os.environ["CODEX_THREAD_ID"])
    for reason in ("event", "timeout", "error"):
        delivery.message(owners, reason, True)
        delivery.message(owners, reason, False)
    return delivery

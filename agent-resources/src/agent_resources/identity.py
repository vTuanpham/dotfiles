"""A request's controller is its exact root conversation, when known."""

import os


def identity():
    explicit = os.environ.get("AGENT_RESOURCES_OWNER")
    if explicit is not None:
        if not explicit or len(explicit) > 400 or any(ord(c) < 33 for c in explicit):
            raise ValueError("invalid resource controller identity")
        return explicit
    keys = (("CLAUDE_CODE_SESSION_ID", "claude"),) if os.environ.get("CLAUDECODE") == "1" else (
        ("CODEX_THREAD_ID", "codex"), ("ANTIGRAVITY_CONVERSATION_ID", "agy"),
        ("CLAUDE_CODE_SESSION_ID", "claude"))
    for name, harness in keys:
        if value := os.environ.get(name):
            if len(value) > 200 or any(ord(c) < 33 for c in value):
                raise ValueError("invalid native controller identity")
            return harness + ":" + value
    return None

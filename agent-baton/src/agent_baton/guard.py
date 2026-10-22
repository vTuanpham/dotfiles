"""PreToolUse hook shared by Claude Code and Codex: exit 2 with a reason on stderr denies the call."""

import json
import re
import sys

from agent_baton import core

HANDBACK = re.compile(r"\bagent[-_]baton\S*\s+(back|cancel)\b")  # the subcommand, not any "back" nearby
OWN_CLI = re.compile(r"^\s*(rtk\s+)?agent-baton\b[^;&|\n$`<>]*$")  # a lone call, nothing chained or nested


def command_of(tool_input):
    if not isinstance(tool_input, dict):
        return ""
    raw = tool_input.get("command") or tool_input.get("cmd") or ""
    return " ".join(raw) if isinstance(raw, list) else str(raw)


def decide(event, cfg, batons):
    """Return the reason to deny this tool call, or None to let it through."""
    name = str(event.get("tool_name", ""))
    tool_input = event.get("tool_input") or {}
    command = command_of(tool_input)
    if command and HANDBACK.search(command):
        return "Only the human hands the baton back or cancels it; run `agent-baton wait` instead."
    if command and OWN_CLI.match(command):
        return None
    browser = re.search(cfg["browser_tools"], name) or (
        command and re.search(cfg["browser_commands"], command)
    )
    if not browser:
        return None
    text = json.dumps(tool_input, ensure_ascii=False).lower()
    for site in cfg["deny"]:
        if site.lower() in text:
            return f"{site} is on the never-browse list; ask the human to do it themselves."
    if batons:
        who = ", ".join(f"{b['site']} ({core.left(b)} left)" for b in batons)
        return (
            f"The baton is with the human for {who}. Do not look at or touch the browser or screen. "
            "The shared screen stays locked across sessions until the human finishes that login."
        )
    return None


def main():
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0  # not a hook payload; nothing to judge
    try:
        reason = decide(event, core.config(), core.held("login", all_sessions=True))
    except Exception:  # noqa: BLE001 - fail closed only while a baton is out
        try:
            reason = (
                "agent-baton guard failed while the baton is out"
                if core.held("login", all_sessions=True)
                else None
            )
        except Exception:  # noqa: BLE001
            reason = None
    if reason:
        print(reason, file=sys.stderr)
        return 2
    return 0

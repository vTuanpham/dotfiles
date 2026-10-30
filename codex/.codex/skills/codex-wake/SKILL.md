---
name: codex-wake
description: Resume idle Codex work after background events, or recover a native worker blocked on an unresponsive idle root. Use when native completion/message delivery has not resumed the target; Bridge watch already delivers its own events.
---

# Codex task notifications

Use the harness's native completion trigger when it already resumes the session.
Otherwise run `codex-wake check`, then use `run` for command completion or `send`
from an existing event producer. This is event delivery, separate from Claude's
visual Wake mod. Bridge watch already delivers its own events; do not wrap it again.

```sh
codex-wake run --message "Tests finished. Review results." -- rtk test uv run pytest
codex-wake run --message "Recheck the pending deployment." -- sleep 180
codex-wake send --message "The awaited file arrived."
```

Start `run` in a persistent background terminal and retain its handle. Continue
independent work; when only the event is pending, end the model turn and let the
notification resume it. A timer in a yielded model-runtime code cell does not
provide that process lifetime. Read the original terminal for command output.

The target defaults to the originating `CODEX_THREAD_ID` and `CODEX_HOME`.
Use `--thread`/`--home` only for an explicitly intended different target. `run`
notifies on success or failure; an existing event producer can call `send`.
Both preflight delivery automatically; `check` diagnoses availability without
sending. On delivery failure, inspect the command's outcome before retrying:
it may already have executed. A notification does not resolve a blocking
question or grant approval.

## Native worker blocked on its root

Use native collaboration messages first and continue independent work. If blocked
after two unanswered messages spaced over at least three minutes:

1. Identify the root from native spawn/parent metadata or the root's explicit
   brief. An inherited `CODEX_THREAD_ID`, a title or the newest thread is not proof
   of parentage. Do not choose another session when identity cannot be verified.
2. Read that exact root through the native task MCP's `read_thread`, keeping
   history/output bounded. Immediately before sending, confirm its reported
   status is `idle`. Silence is not an idle check; `active`, `notLoaded`, errors
   and unknown states do not qualify. Respect a user pause and pending human input
   or approval.
3. Use the same MCP's `send_message_to_thread` once, with the verified root's
   `threadId` and a short `prompt` identifying the worker, blocker and requested
   decision. Omit model overrides. This is the native task channel used by
   `codex-wake`; no separate wake process is needed inside the harness.
4. Verify the returned target and return to native messages/waits. Send at most
   one recovery wake per unresolved blocker; an uncertain receipt is not a reason
   to duplicate it. This never answers a question or grants approval.

For installation, producers and compatibility details, see
`~/dotfiles/codex-wake/README.md`.

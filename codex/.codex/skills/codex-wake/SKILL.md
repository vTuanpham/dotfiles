---
name: codex-wake
description: Deliver task notifications to the originating Codex conversation from background command completion, timers or external events. Use to resume idle work when no native completion trigger handles it; Bridge watch already delivers its own events.
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

For installation, producers and compatibility details, see
`~/dotfiles/codex-wake/README.md`.

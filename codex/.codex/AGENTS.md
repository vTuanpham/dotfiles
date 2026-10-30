Read `~/.config/agents/AGENTS.md` before starting work and apply its shared
instructions alongside this file's Codex preferences.

## Background task notifications

Use the `codex-wake` skill when background command completion, a timer or an
external event should resume this conversation and no native completion trigger
already does. Read the skill before launching: it covers delivery preflight,
originating-session targeting and a background process that survives ending the
turn. Bridge watch already delivers its own events; do not wrap it again.
Notifications never answer a pending question or grant approval.

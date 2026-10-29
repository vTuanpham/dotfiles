# Codex root watch delivery

Ordinary `agent-bridge watch OWNER --until-event --timeout 1800` detects a
Codex root and delivers native task notifications automatically. Run it as a
background command while doing independent work, or wait directly when idle.
`watch: native Codex root delivery ready` confirms the startup check. No
root-managed timer, polling loop, MCP call, or extra watch flag is needed.

## Implementation and troubleshooting

`root_wake.py` detects the current `CODEX_THREAD_ID`, excluding bridge workers
and Claude roots. It uses the current Codex home's local app-server control
socket and verifies `codex_tui.send_message_to_thread` before consuming events.
At each returned event, timeout, or observer error, it opens a fresh connection
and calls the native tool for that same thread. This works after the model turn
ends; a yielded model-runtime code cell is not the adapter.

The [app-server MCP API](https://learn.chatgpt.com/docs/app-server) owns
initialization and `mcpServer/tool/call`. The adapter checks the observed native
tool's returned thread receipt, in addition to the outer MCP result. A missing
tool, rejected call, invalid receipt, or transport error fails visibly. It never
substitutes [`codex queue`](https://learn.chatgpt.com/docs/developer-commands#codex-queue),
which creates a user-style prompt instead of a native task-message envelope.
Callback messages are notifications, never user approval. Grouping, unread
reminders and acknowledgments remain owned by the shared watch policy.

When `--until-event` reaches a wake, Codex receives a native task message. If the
snapshot still has a scheduled reminder or held group completion, that same OS
process continues watching after the first message and delivers each due wake.
After acknowledgements clear the schedule or a one-shot reminder is delivered,
the watch returns to ordinary observation; if workers remain, the original
`--timeout` deadline applies. It exits when no jobs or scheduled wakes remain,
the deadline expires, or the owner is handed off. It can wait for
a scheduled reminder even if no earlier wake occurred, and can outlive `--timeout`
while that schedule is pending. Without a scheduled wake, the timeout still applies.
This continuation is Codex-specific: the root should re-arm after
an event when jobs remain but no schedule is pending, and other harnesses still
need a re-armed watch for later reminders. An empty, fully handled owner exits
silently. Native delivery marks notices seen only after acceptance, under the
existing owner lock; an uncertain transport outcome can redeliver on retry.
Reminder deadlines persist in group state and a restarted watch can replay a due
reminder, but no supervisor restarts a process killed by a hard failure or signal.

# Native Codex workers

Use the native collaboration tools exposed by this session. Their schema owns
available models, effort, concurrency and context-fork behavior; do not copy
Bridge model IDs or command flags into native calls.

The official configuration can select subagent models/effort or inherit the
parent. Where a full-history fork requires inherited model/effort, use a fresh,
self-contained brief for an explicitly supported override.
Applicable user and harness restrictions still govern whether overrides are allowed.

Use native messages/follow-ups to continue a related worker. An idle worker is
reusable; interrupt it when needed, and use the documented wait operation when
no useful independent work remains. Preserve file ownership across follow-ups.
Do not route native Codex work through Bridge or create a second Codex process.

If repeated native messages leave a worker blocked on an idle root, use the
`codex-wake` skill's bounded parent-recovery workflow. A root briefing a worker
that may need this recovery should include its native thread ID when available.

Source: [Codex subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents).

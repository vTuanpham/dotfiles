# Native Antigravity workers

Use the current native subagent tools and supported agent definitions. CLI and
IDE capabilities can differ: the native schema/agent configuration owns accepted
model tiers, permissions, workspace choices and lifecycle controls. A model that
`agy models` lists is not necessarily selectable by a native subagent tier.

Give a complete brief when the worker starts without the parent's conversation.
Choose shared workspace or isolated worktree according to file ownership. Keep
tool names exact; the documentation warns that invalid allowed-tool names can
hang a custom agent.

Use native messages for related follow-ups: idle agents can resume, killed agents
cannot. Use native completion/event delivery when exposed. If the current tool
backgrounds long commands without a completion trigger, run a bounded event wait
or hand the command to the root; avoid repeated model-driven status polling.

Source: [Antigravity subagents](https://antigravity.google/docs/subagents).

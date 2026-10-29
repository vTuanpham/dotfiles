# opencode

[← Packages](../README.md#packages) · **Snapshot + live** · `./install.sh --apply snapshots links`

OpenCode's user config under `~/.config/opencode`.

- `AGENTS.md`: **live** link to the shared instructions (`agents/`).
- `cli.json`: interface preferences (word-wrapped diffs, no sidebar). A snapshot.
- `opencode.jsonc`: the schema line only; no model or provider is pinned here. A snapshot.

Shared skills, including `python-project` and the adapted
[engineering skills](../agents/README.md#engineering-skills), are discovered from
`~/.agents/skills`. They use available native tools and load only for relevant
tasks; no separate copy of their workflows belongs in the global instructions.

`agent-bridge` runs OpenCode workers confined by `bwrap`, and only on the zero-retention free models
listed in `agent-bridge guide subscriptions` (read when plan or retention terms matter).

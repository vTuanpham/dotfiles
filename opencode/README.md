# opencode

[← Packages](../README.md#packages) · **Snapshot + live** · `./install.sh --apply snapshots links`

OpenCode's user config under `~/.config/opencode`.

- `AGENTS.md`: **live** link to the shared instructions (`agents/`).
- `cli.json`: interface preferences (word-wrapped diffs, no sidebar). A snapshot.
- `opencode.jsonc`: the schema line only; no model or provider is pinned here. A snapshot.

`agent-bridge` runs OpenCode workers confined by `bwrap`, and only on the zero-retention free models
listed in `agent-bridge guide subscriptions` (read when plan or retention terms matter).

# opencode

[← Packages](../README.md#packages) · **Snapshot + live** · `./install.sh --apply snapshots links`

OpenCode's user config under `~/.config/opencode`.

The installer restores OpenCode 2.2.2 from its official V2 installer, matching
the inbox adapter's verified protocol.

- `AGENTS.md`: **live**, appendable OpenCode preferences.
- `cli.json`: interface preferences (word-wrapped diffs, no sidebar). A snapshot.
- `opencode.jsonc`: loads shared instructions via the native
  [`instructions` field](https://opencode.ai/docs/rules/#custom-instructions).
  No model or provider is pinned here. A snapshot.
- `plugins/agent-process-guard.js`: **live**, a native OpenCode 2 before-tool
  plugin (OpenCode 2.2.2+) that calls the shared [process guard](../shell/README.md#agent-process-matching)
  for `shell` commands. It is discovered automatically under the global plugin directory.

Shared skills, including `python-project` and the adapted
[engineering skills](../agents/README.md#engineering-skills), are discovered from
`~/.agents/skills`. They use available native tools and load only for relevant
tasks; no separate copy of their workflows belongs in the global instructions.

`agent-bridge` runs OpenCode workers confined by `bwrap`, and only on the zero-retention free models
listed in `model-guide read subscriptions` (read when plan or retention terms matter).

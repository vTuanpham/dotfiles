# rtk

[← Packages](../README.md#packages) · **Snapshot** · `./install.sh --apply snapshots`

The user config for [RTK](https://github.com/rtk-ai/rtk), the proxy that filters shell
command output before it reaches an agent.

- `.config/rtk/config.toml`: tracking and history settings.
- `.config/rtk/filters.toml`: user-global output filters; a project's own `.rtk/filters.toml` takes
  precedence over these.

The Claude and Codex configs call `rtk hook claude` as a `PreToolUse` hook, and the shell startup test
needs `rtk` on PATH. There is no scripted install: install it by hand.

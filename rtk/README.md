# rtk

[← Packages](../README.md#packages) · **Snapshot** · `./install.sh --apply snapshots`

The user config for [RTK](https://github.com/rtk-ai/rtk), the proxy that filters shell
command output before it reaches an agent.

- `.config/rtk/config.toml`: tracking and history settings.
- `.config/rtk/filters.toml`: user-global output filters; a project's own `.rtk/filters.toml` takes
  precedence over these.

The Claude and Codex configs call `rtk hook claude` as a `PreToolUse` hook, and the shell startup test
needs `rtk` on PATH. There is no scripted install: install it by hand.

The `uvx-progress` filter removes UVX setup progress, preserving tool output,
package changes, errors and exit status. It does not filter Baton answers,
Bridge events or protocol JSON. After reviewing and copying the snapshot to the
live config, run `rtk trust --yes` locally. Trust hashes stay outside Git.
Use `rtk uvx ...` for standalone UV-managed tools; repository commands stay
`uv run` with the existing RTK filters.

## Exact output and shell quoting

`rtk proxy` bypasses output filtering. Use it for exact protocol/instruction
output or commands with shell operators/comparisons that a filtering wrapper
may reconstruct incorrectly. A recorded `rtk summary` invocation stripped the
quoting from `awk 'NR>=80'`, leaving a `>=80` redirect and a stray `=80` file.
Prefer a read tool for line ranges; recover omitted output with `rtk recall` or
a focused read. Ordinary commands still use the appropriate RTK filter.

## Checks

Run `python3 -B tests/test_rtk_filters.py` from the repo root to check the inline
fixtures and real dispatch/exit status in an isolated config. RTK's verifier
currently reads project filters, not global ones, so an empty global verify run
is not proof that a filter passed. The test copies this snapshot into its own
temporary project and keeps its trust state there.

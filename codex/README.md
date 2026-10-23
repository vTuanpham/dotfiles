# codex

[← Packages](../README.md#packages) · **Snapshot + live** · `./install.sh --apply snapshots links hooks`

Codex CLI config under `~/.codex`.

- `AGENTS.md`: **live** link to the shared instructions (`agents/`).
- `config.toml`: model, agents, plugins, features and the status line. A snapshot. Machine-local state
  (trusted projects, hook trust hashes, UI hints) is deliberately not tracked; Codex asks again.
- `hooks.json`: the `PreToolUse` hooks (`rtk hook claude`, `agent-baton guard`). `install.sh --apply hooks`
  adds any that the live `~/.codex/hooks.json` lacks, keeping the rest; Codex then asks you to trust them
  with `/hooks`.
- The `ponytail` plugin is enabled in `config.toml` (`[plugins."ponytail@ponytail"]` and
  `[marketplaces.ponytail]`); see "Plugin: ponytail" in the top-level README. Its own hooks are not tracked
  here; Codex asks you to trust them with `/hooks`.
- `preferred-codex-settings.config.toml`: an alternative set of preferred model and effort settings.
- `model-catalogs/`: the generated model catalog's overrides and its hourly refresher; see its README. The
  generated catalog itself is not tracked.

[Agent Bridge](../agent-bridge/README.md) drives Codex workers;
the separate `codex-auth` tool manages account selection and reads locally cached quota.

Chrome control in WSL uses a locally registered `node_repl` MCP server and the
app's unchanged Chrome skill. The [browser adapter guide](../chrome/README.md#chatgpt-from-wsl-gap-and-local-compatibility-patch)
owns its setup and Windows kernel exception. Machine paths and authorization
stay in the live config; future chats use the native browser tools directly.

## Questions and reminders

For questions, prefer the native asynchronous tool when available, following the
[shared reminder policy](../agent-baton/README.md#native-questions-and-hooks).
Background hooks cannot resolve an already-running tool or wake an idle turn;
no question-cancellation hook is installed here.
[OpenAI hooks reference](https://learn.chatgpt.com/docs/hooks#run-hooks-in-the-background).

## Native integrations

Native Baton and GitHub servers use the installed `agent-baton mcp` and
`github-mcp` commands. Reload MCP configuration after installing them; the
[Baton guide](../agent-baton/README.md#commands) owns conversation isolation,
and [GitHub setup](../github/README.md) owns credentials and read-only toolsets.
The old GitHub plugin server is disabled to avoid a duplicate unauthenticated
connection. Tokens and host paths remain local.

## Cache and resuming threads

| Route | Returning to old context |
| --- | --- |
| Signed-in Codex / Work | [Announced as "cache forever"](https://x.com/thsottiaux/status/2112712984644784534): no time-based cache penalty when returning to old conversations. |
| Direct API requests | [Model-specific cache lifetimes](https://developers.openai.com/api/docs/guides/prompt-caching#cache-lifetime) still apply. |

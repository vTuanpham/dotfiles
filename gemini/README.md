# gemini

[← Packages](../README.md#packages) · **Live + merged hooks** · `./install.sh --apply links hooks`

Antigravity CLI (`agy`) configuration:

- `.gemini/AGENTS.md`: an appendable Antigravity global file. Its
  [native include](https://antigravity.google/docs/rules#file-includes) loads the
  shared instructions (`agents/`) before any Antigravity preferences.
- `.gemini/config/skills/agent-bridge` and `.../agent-baton`: the shared skills.
- The nine [pstack engineering skills](../agents/README.md#engineering-skills) link directly from `agents/`.
- The shared `python-project` skill also links from `agents/`.
- `.gemini/config/hooks.json`: named hooks merged additively by
  `./install.sh --apply hooks`. The shared [process guard](../shell/README.md#agent-process-matching)
  checks `run_command` automatically; `/hooks` shows active hooks. Existing named
  hooks and local disabled overrides are preserved.

The CLI's own `~/.gemini/antigravity-cli/settings.json` (permission grants, trusted workspaces) is not
tracked because it lists local project paths. See [Agent Bridge's root-access setup](../agent-bridge/README.md#restore-and-root-access)
for its machine-local grants.

## Cache and thread reuse

No fixed prompt-cache TTL is established here. Use the harness's actual usage
reporting rather than importing another provider's cache lifetime. Keep related
context when it is useful; start fresh for unrelated or oversized conversations.

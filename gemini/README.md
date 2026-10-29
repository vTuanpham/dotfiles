# gemini

[← Packages](../README.md#packages) · **Live** · `./install.sh --apply links`

Antigravity CLI (`agy`) links:

- `.gemini/AGENTS.md`: the shared instructions (`agents/`).
- `.gemini/config/skills/agent-bridge` and `.../agent-baton`: the shared skills.
- The nine [pstack engineering skills](../agents/README.md#engineering-skills) link directly from `agents/`.
- The shared `python-project` skill also links from `agents/`.

The CLI's own `~/.gemini/antigravity-cli/settings.json` (permission grants, trusted workspaces) is not
tracked because it lists local project paths. See [Agent Bridge's root-access setup](../agent-bridge/README.md#restore-and-root-access)
for its machine-local grants.

## Cache and thread reuse

No fixed prompt-cache TTL is established here. Use the harness's actual usage
reporting rather than importing another provider's cache lifetime. Keep related
context when it is useful; start fresh for unrelated or oversized conversations.

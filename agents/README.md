# agents

[← Packages](../README.md#packages) · **Live** · `./install.sh --apply links`

The instructions and skills every coding agent shares.

- `.config/agents/AGENTS.md`: the one owner of the rules all harnesses share. Put harness-specific rules in
  that harness's own file, never here.
- `.agents/skills/agent-bridge/SKILL.md` and `.agents/skills/agent-baton/SKILL.md`: short briefings that say
  what each tool is and when to reach for it. The full workflow prints from `agent-bridge --help` and
  `agent-baton --help`, so an agent reads it only when it decides to.

How each harness reaches them: Codex `~/.codex/AGENTS.md`, OpenCode `~/.config/opencode/AGENTS.md` and
Antigravity `~/.gemini/AGENTS.md` are in-repo symlinks to the shared file (none of them imports files).
Claude's `CLAUDE.md` imports it with `@~/.config/agents/AGENTS.md`. Codex finds the skills in
`~/.agents/skills`, Claude in `~/.claude/skills`, Antigravity in `~/.gemini/config/skills`, through links in
their packages.

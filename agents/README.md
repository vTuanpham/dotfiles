# agents

[← Packages](../README.md#packages) · **Live** · `./install.sh --apply links`

The instructions and skills every coding agent shares.

Manual recovery backups live outside Git under
`${XDG_STATE_HOME:-$HOME/.local/state}/backups/<scope>/<timestamp>/`, with private
permissions and original paths/restore details. A scope can be a tool, project,
system, or cross-tool change; bundles can contain files, directories, or archives.
Application-managed rotating backups stay in the application's own location.

- `.config/agents/AGENTS.md`: the one owner of the rules all harnesses share. Put harness-specific rules in
  that harness's own file, never here.
- `.agents/skills/agent-bridge/SKILL.md` and `.agents/skills/agent-baton/SKILL.md`: short briefings that say
  what each tool is and when to reach for it. The full workflow prints from `agent-bridge guide workflow` and
  `agent-baton --help`, so an agent reads it only when it decides to.
  Bridge's `steer` resumes idle jobs automatically; `--queue` leaves them queued
  for an explicit `resume`, and `--watch` follows delivery in the same command.

How each harness reaches them: Codex `~/.codex/AGENTS.md`, OpenCode `~/.config/opencode/AGENTS.md` and
Antigravity `~/.gemini/AGENTS.md` are in-repo symlinks to the shared file (none of them imports files).
Claude's `CLAUDE.md` imports it with `@~/.config/agents/AGENTS.md`. Codex finds the skills in
`~/.agents/skills`, Claude in `~/.claude/skills`, Antigravity in `~/.gemini/config/skills`, through links in
their packages.

## Engineering skills

Nine [pstack](https://github.com/backnotprop/pstack) skills are vendored unchanged
at commit [`fad8d01588a1`](https://github.com/backnotprop/pstack/tree/fad8d01588a1b1ae803f87c8a1e0de79e28cffec),
with their references and [MIT license](PSTACK-LICENSE). The installer links each
directory into `~/.agents/skills`, `~/.claude/skills` and
`~/.gemini/config/skills`. Codex and OpenCode discover the shared `.agents` path.

| Use | Skills |
| --- | --- |
| Prevent repeated mistakes | `correct` |
| Check performance measurements | `benchmark-checklist` |
| Create and maintain project verification recipes | `create-verification-skill`, `maintain-verification-skill` |
| Explain behavior and design rationale | `how`, `why` |
| Investigate change risks | `blast-radius` |
| Compare alternatives and edit prose | `arena`, `unslop` |

Use these on demand, under the shared scope, permission and delegation rules.
The full `poteto-mode` plugin is not installed. To update, review a new upstream
revision and replace these nine directories together, retaining the license and
updating the pinned commit here.

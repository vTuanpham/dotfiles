# agents

[← Packages](../README.md#packages) · **Live** · `./install.sh --apply links`

Shared guidance and task skills for Codex, Claude Code, Antigravity and OpenCode.
The [repository placement policy](../AGENTS.md#guidance-placement) governs changes:
keep enough context to choose and execute correctly, with one owner for details.

## Instruction and skill map

| Scope | Maintained source | Live discovery |
| --- | --- | --- |
| Shared globals | `.config/agents/AGENTS.md` | All four harnesses |
| Codex globals | [codex/.codex/AGENTS.md](../codex/.codex/AGENTS.md) | `~/.codex/AGENTS.md`; currently links to shared globals |
| Claude globals | [claude/.claude/CLAUDE.md](../claude/.claude/CLAUDE.md) | `~/.claude/CLAUDE.md`; imports shared globals and adds Claude preferences |
| Antigravity globals | [gemini/.gemini/AGENTS.md](../gemini/.gemini/AGENTS.md) | `~/.gemini/AGENTS.md`; currently links to shared globals |
| OpenCode globals | [opencode/.config/opencode/AGENTS.md](../opencode/.config/opencode/AGENTS.md) | `~/.config/opencode/AGENTS.md`; currently links to shared globals |
| Shared skills | `.agents/skills/` | Codex/OpenCode: `~/.agents/skills`; Claude: `~/.claude/skills`; agy: `~/.gemini/config/skills` |
| Codex-only skills | [codex/.codex/skills/](../codex/.codex/skills/) | `~/.codex/skills`; includes `codex-wake` |

A harness-specific global file is allowed when a preference belongs in every
session of that harness. The current shared symlinks are not places to append
one harness's override. Use supported composition or a scoped skill, preserving
the shared file's ownership. Project-local instructions own project invariants.

Skill names/descriptions provide discovery; the body supplies the workflow.
Keep the first action and non-obvious constraints there. Load references only for
the selected mode, and use CLI help for changing flags/defaults. Prefer an
enforced contract or native tool behavior when it can replace a remembered rule.

## Shared tools

- `agent-bridge`: root coordination across harnesses. Its skill routes to
  `agent-bridge guide workflow`, which owns launch/watch/group/cleanup behavior.
  Backend notes and CLI discovery own available models and flags.
- `agent-baton`: secret handoffs and unanswered-question reminders. Its skill
  retains secret handling, conversation isolation and target-focus constraints;
  `agent-baton --help` owns forms and command schemas.
- `python-project`: the substantial Python baseline, including uv, type checking,
  quality tools and CI. Small scripts and narrow fixes keep proportional scope.

The global rules retain authorization, question escalation, ownership,
verification and boundary safety. Detailed language-specific workflows belong
to their skills. Harness-specific cache notes live in
[Codex](../codex/README.md#cache-and-resuming-threads),
[Claude](../claude/README.md#cache-and-thread-reuse) and
[Antigravity](../gemini/README.md#cache-and-thread-reuse).

## Engineering skills

Nine [pstack](https://github.com/backnotprop/pstack) skills are based on commit
[`fad8d01588a1`](https://github.com/backnotprop/pstack/tree/fad8d01588a1b1ae803f87c8a1e0de79e28cffec),
with their references and [MIT license](PSTACK-LICENSE). They are locally adapted:
native tools/model discovery replace Cursor-specific calls and guessed model
slugs; absent companion skills are not required; searches and delegation fit the
task; commits/publication retain the user's authorization boundary.

| Use | Skills |
| --- | --- |
| Prevent recurring repository mistakes | `correct` |
| Validate measured performance claims | `benchmark-checklist` |
| Create or audit app verification workflows | `create-verification-skill`, `maintain-verification-skill` |
| Explain execution or historical rationale | `how`, `why` |
| Assess risk beyond a diff | `blast-radius` |
| Compare requested candidates or edit prose | `arena`, `unslop` |

Automatic matching is enabled; descriptions narrow when a workflow is relevant.
A skill's availability does not authorize extra agents, product edits or external
actions. The full upstream plugin is not required or installed. To refresh the
vendored skills, review upstream against the pinned baseline, preserve local
scope/portability adaptations and license, then update the attribution.

Manual recovery backups remain outside Git under
`${XDG_STATE_HOME:-$HOME/.local/state}/backups/<scope>/<timestamp>/`, with private
permissions and original paths/restore details. Application-managed backups stay
in their own locations.

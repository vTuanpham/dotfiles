# agents

[← Packages](../README.md#packages) · **Live** · `./install.sh --apply links`

Shared guidance and task skills for Codex, Claude Code, Antigravity and OpenCode.
The [repository placement policy](../AGENTS.md#guidance-placement) governs changes:
keep enough context to choose and execute correctly, with one owner for details.

[Host feedback workflow and public templates](feedback/README.md) support private
local issues and comments. Only agents working on dotfiles review that queue;
the shared global guidance asks other agents to report relevant tooling friction.

## Instruction and skill map

| Scope | Maintained source | Live discovery |
| --- | --- | --- |
| Shared globals | `.config/agents/AGENTS.md` | All four harnesses |
| Codex globals | [codex/.codex/AGENTS.md](../codex/.codex/AGENTS.md) | `~/.codex/AGENTS.md`; reads shared globals, then Codex preferences |
| Claude globals | [claude/.claude/CLAUDE.md](../claude/.claude/CLAUDE.md) | `~/.claude/CLAUDE.md`; imports shared globals and adds Claude preferences |
| Antigravity globals | [gemini/.gemini/AGENTS.md](../gemini/.gemini/AGENTS.md) | `~/.gemini/AGENTS.md`; includes shared globals, then agy preferences |
| OpenCode globals | [opencode/.config/opencode/AGENTS.md](../opencode/.config/opencode/AGENTS.md) | `~/.config/opencode/AGENTS.md`; combined with shared globals by `opencode.jsonc` |
| Shared skills | `.agents/skills/` | Codex/OpenCode: `~/.agents/skills`; Claude: `~/.claude/skills`; agy: `~/.gemini/config/skills` |
| Codex-only skills | [codex/.codex/skills/](../codex/.codex/skills/) | `~/.codex/skills`; includes `codex-wake` |

Each harness owns an appendable global file. Claude and Antigravity import the
shared source; OpenCode loads it through its native `instructions` config.
Codex explicitly reads it because its global instruction loader has no documented
include directive. Append only harness-wide preferences; project invariants stay
in project instructions.

Skill names/descriptions provide discovery; the body supplies the workflow.
Keep the first action and non-obvious constraints there. Load references only for
the selected mode, and use CLI help for changing flags/defaults. Prefer an
enforced contract or native tool behavior when it can replace a remembered rule.

## Shared tools

- `model-selection`: model/effort choices for main sessions or workers, backed by
  `model-guide` and its independently maintained references.
- `delegation`: shared worker planning and verification, with native harness
  references loaded only when needed. Bridge is its cross-harness execution route.
- `agent-bridge`: root coordination across harnesses. Its skill routes to
  `agent-bridge guide workflow`, which owns launch/watch/group/cleanup behavior.
  Backend notes and CLI discovery own available models and flags.
- `agent-baton`: secret handoffs and unanswered-question reminders. Its skill
  retains secret handling, conversation isolation and target-focus constraints;
  `agent-baton --help` owns forms and command schemas.
- `python-project`: the substantial Python baseline, including uv, type checking,
  quality tools and CI. Small scripts and narrow fixes keep proportional scope.
- `agent-lab`: persistent experiments outside repositories, with creator/latest-run
  provenance, size warnings and retirement. Its CLI owns layout and cleanup checks.
- `resource-admission`: heavy foreground work from any harness, using the independent
  agent-resources queue rather than requiring Bridge orchestration.

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

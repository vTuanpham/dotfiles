---
name: delegation
description: Choose and coordinate native subagents or cross-harness workers for authorized parallel work, independent reviews and follow-ups. Routes briefing and lifecycle guidance to the relevant harness.
---

# Delegation

Delegate only work that benefits from independent progress or scrutiny. Keep
coupled work together and give concurrent writers disjoint ownership.

For model/effort tradeoffs, use the `model-selection` skill. The current native
tool's exposed models and controls take precedence over dated reference advice.
Choose each worker's model and effort for its task; set them explicitly where
supported. Use inherited/default settings only when they suit that work, not
because they are the default.

Choose the execution route, then read only its relevant reference:

- Same harness: [Codex](references/codex.md), [Claude](references/claude.md),
  [Antigravity](references/antigravity.md), or [OpenCode](references/opencode.md).
- Another harness, model or quota pool: use the `agent-bridge` skill. It owns
  persistent job launch, watch, steering, recovery and retirement.

Brief the objective, evidence/context, owned files, constraints, checks and
expected output. Name only supporting docs the worker needs. State whether it
may edit; delegation never expands commit, publication or spending authority.
Use an isolated worktree for independent writers when they need one.
For heavy worker commands, the resource-admission skill owns host queue usage.

Keep useful independent work moving. Reuse a worker for related follow-ups;
start fresh for unrelated work or a heavy context. Match waits to expected work
and native limits: about 60 seconds for an answer, or 3–5 minutes for progress
when idle and permitted. Return early for updates. Workers report blockers,
coordination needs, actionable findings and completion; skip routine acknowledgements.
Cache policy belongs to harness docs; cache cost does not justify mixing
unrelated work in an old thread.

Verify claims against source and inspect the diff/check results. Small-model
output needs a root spot-check and an independent review before integration;
larger models still need verification, with independent review for risky changes.
Keep worker context while follow-up or verification needs it, then clean up
through that route's lifecycle controls.

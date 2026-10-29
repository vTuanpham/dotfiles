---
name: arena
description: Compare parallel solution candidates and combine their strongest parts. Use when the user requests /arena, an arena comparison or competing implementations.
license: MIT
---

# Arena

Produce one coherent result from independent alternatives. An arena request
authorizes the requested comparison, not unrelated jobs or external publication.

## Frame

State the deliverable, constraints and a small concrete evaluation rubric.
Give candidates the same task brief and separate output locations, preferably
worktrees for code. Use the user's model/effort choices and the current harness's
available native agents. Without specified models, inherit rather than guessing
vendor-specific slugs. Load agent-bridge only when another harness is needed.

## Generate and judge

Launch independent candidates concurrently within resource limits. Each returns
its artifact and a short explanation of its choices. If one fails to produce,
assess the remaining candidates and report that limitation.

After writing finishes, use an independent read-only judge when authorized
resources permit. Give it the rubric and candidate paths; avoid disclosing which
one you favor. Read every candidate yourself and compare concrete criteria with
the judge's findings. Investigate disagreements rather than averaging scores.

## Combine

Choose the base a future maintainer can extend and whose constraints hold.
Inspect each alternative for useful parts; adapt those parts to the base's
contracts instead of mechanically combining incompatible implementations.
Convergence needs no forced graft. If candidates answer different questions,
clarify the brief before another round.

## Verify and hand off

Run the checks appropriate to the final artifact and inspect rendered visuals
when relevant. Resolve findings in the same owned scope. Preserve needed work
before cleaning temporary outputs/worktrees. Report the chosen base, useful
grafts, rejected tradeoffs, limitations and verification; commit/publish only
within the user's authorization.

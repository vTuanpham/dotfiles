---
name: blast-radius
description: Review what a change could break beyond its diff and prove the safety assumptions with real code. Use for blast-radius questions or a requested review of risky shared behavior.
license: MIT
---

# Blast radius

Find the breakage that a caller search alone will miss. Read the changed symbols
and connected code, including contracts the diff does not show.

1. Identify what changed and the one or two facts its safety depends on.
2. Follow consumers across persistence/wire formats, services, languages,
   lifecycle order, feature flags, configuration and pinned dependency behavior.
   Read the actual library version or local patch when the claim depends on it.
3. Give likely failures a concrete trigger, effect and source location.
   Distinguish confirmed risks from plausible but unproven ones.
4. Prove important safety facts by running the real code: a focused existing
   test, a small scratch repro or a live user path. A line citation supports a
   mechanism; it does not by itself prove the change safe.
5. Report the behavior change, proved assumptions, remaining risks and the
   cheapest checks needed before shipping. Cite cleared concerns when useful;
   do not pad the report with speculative callers or empty sections.

Evidence strengthens from a claim, to a source citation, to tracing why a bad
case cannot occur, to an executable check, to a live reproduction. State where
the evidence actually stops. Never describe an unrun proof as verified.

For broad changes, authorized independent review can add scrutiny; use native
agents or a requested arena. A review alone does not authorize product edits,
commits or publication. Keep public reports free of private details.

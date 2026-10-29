---
name: why
description: Investigate code history, design rationale, regressions or the evidence behind a threshold. Use when the user asks why a decision was made; use how for execution flow.
license: MIT
---

# Why

Answer the user's rationale question from evidence. Code shows mechanics, not
author intent. Separate direct evidence, supported conclusions, inference,
speculation and unknowns; [epistemics](references/epistemics.md) defines the tiers.

1. Identify the target files/symbols and the actual question. Follow relevant
   git history/blame, commit messages and linked PRs or tickets. Do not assume a
   GitHub remote, CLI login or external source exists.
2. Discover available connectors/tools, then search the sources relevant to the
   decision. A direct answer in a PR may be enough; a disputed or cross-system
   decision needs wider corroboration. Use the
   [source index](references/source-playbook.md) to select only applicable guides.
   Defensive code may also need its linked incident history.
3. Read the evidence in context, follow material leads and record the searches.
   Surface contradictions and missing access. Do not search every account,
   warehouse or chat merely because a connector is installed.
4. Synthesize with citations. Verify important claims and distinguish stated
   motivation from your interpretation. Test hypotheses in the user's question
   instead of adopting them. Name material unanswered questions and coverage gaps.
5. Give a concise answer for a narrow question. For a larger investigation,
   organize findings, alternatives, unknowns and sources; when a change follows,
   state what the evidence says to preserve, change or avoid.

Investigate directly unless independent source work merits authorized delegation.
Use the harness's available tools/model choices; no preset agent names or model
slugs are required. Give delegated roles only the access needed for their source;
investigation does not authorize writes or external messages. Optional templates:
[investigator](references/investigator-prompt.md) and
[synthesis](references/synthesizer-prompt.md). Keep their evidence discipline;
scale their sections to the question.

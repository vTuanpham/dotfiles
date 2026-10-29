---
name: how
description: Explain code architecture, execution flow, ownership or placement from source. Use for code walkthroughs and "how does this work" questions; use why for historical motivation.
license: MIT
---

# How

Trace the relevant source and explain enough of the subsystem for someone to
work on it. Match depth to the question: a narrow function question rarely
needs a full architecture report.

1. Identify the entry point, important types and the boundary the question
   concerns. Use the conversation to resolve a vague target and state your reading.
2. Follow the real call/data path, including callers, configuration and external
   contracts that affect it. Cite files and symbols; distinguish observed
   behavior from assumptions or unresolved paths.
3. Explain what triggers the flow, where state lives, important decisions and
   non-obvious failure/cleanup behavior. Use a diagram when it clarifies the flow.
4. Present the answer at the requested depth, with a short file map when useful.
   Skip empty sections and annotated-source dumps.

For a larger investigation, split independent angles only when delegation is
authorized and useful. Use available native subagents and current model choices;
otherwise investigate the angles yourself. The optional
[explorer](references/explorer-prompt.md) and
[explainer](references/explainer-prompt.md) templates preserve useful handoff
structure; load them only when using those roles. Read-only work stays read-only,
and findings must be checked against source before presentation.

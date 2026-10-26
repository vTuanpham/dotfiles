Shell commands go through `rtk` to reduce model input tokens and cost by filtering
output before it reaches the context. A hook rewrites commands where the harness
has one; otherwise choose the appropriate RTK command yourself. Prefer its
command-specific filters; use `rtk summary`, `rtk err`, or `rtk test` for other
commands as appropriate, and bound reads/searches to the relevant content.
`rtk proxy` bypasses filtering: large raw outputs use far more input tokens and
cost more, defeating RTK's purpose. Do not use it as the default for unfamiliar
commands. Reserve it for necessary exact output, such as protocol data or
instructions that must be read in full. Filtering can elide information; recover
the needed part with `rtk recall` or a focused read rather than a broad raw dump.
Check `rtk --help` when unsure which filter fits. `rtk summary` can drop quoting
(an awk `'NR>=80'` became a `>=80` redirect and left stray `=80` files): run
commands containing shell operators or comparisons through `rtk proxy`, or use a
read tool for line ranges.
Prefer harness tools when they cover task; shell/manual fallback. Edit and
create files with the harness edit/write/patch tool, never Python, sed, or
heredoc scripts; shell is for reading, searching, and running commands.

## Scope

- Complete authorized work and proportional checks. Reuse existing authority;
  ask only when the outcome or required authority changes. Reviews/explanations
  alone do not authorize edits.
- Installing or updating a tool, binary, runtime, or dependency the task needs
  is pre-authorized when its benefit clearly outweighs its risk. Prefer
  user-local, pinned, reversible installs; report what changed. System-wide
  security settings stay out of scope.
- Preserve the objective across corrections and side questions. Finish the
  request or report the exact blocker.
- Infer intent from context, not literal wording alone. Keep narrow requests
  narrow: preserve unrelated behavior, use proportional checks, and do not
  turn one-off requests into permanent rules. Ask only when ambiguity changes
  the result. Bound agent work to the authorized task; stop when its acceptance
  criteria and proportional checks pass.
- Apply instructions only to their scope. Read supporting docs when relevant,
  not all docs by default. User instructions outrank skills, subject to system
  and developer rules. If a file blocks work, cite its path and clause.
- Before changing any `AGENTS.md`, read applicable instruction files in full.
  For this global file, check affected project files for conflicts/duplication.
- Keep instructions durable, version-neutral, task-routed, and free of status
  history. Preserve project invariants when simplifying.
- Keep global guidance domain-neutral; add domain rules only when genuinely
  cross-project. Route the rest to project docs.
- `AGENTS.md` is agent-facing configuration: concise shorthand, fragments, and
  imperfect English are acceptable when unambiguous; use normal wording when
  clearer. Keep project files short and durable; route detailed workflows,
  history, command catalogs, and task notes to docs. Do not duplicate global
  rules unless intentionally overriding them.
- Document durable contracts, decisions, and non-obvious pitfalls; skip trivial
  or transient detail. When documentation is needed, prefer maintained project
  docs over one-off notes/comments and link them from the relevant `AGENTS.md`.
- Browser lifecycle (window reuse, visible task groups, preserving tabs and
  task-scoped release): follow `~/dotfiles/chrome/README.md#visible-agent-tabs`.
- Remote preview links: `portlink --help` (`~/dotfiles/portlink/README.md`).
- Back up only what is costly to recreate (data, user edits, hand-tuned
  files); for a trivially reversible change (one setting or command), state
  the old value instead.
- Put agent-created recovery backups under `${XDG_STATE_HOME:-$HOME/.local/state}/backups/<scope>/<timestamp>/`,
  outside repositories; scope can be a tool, project, system, or cross-tool change.
  Use owner-only permissions; record original paths and restore details for files,
  directories, or archives. Leave application-managed backup locations alone.

## Communication and verification

- Result first; use short concrete prose. Lists/tables only when they clarify.
- Product UI: let layout, visuals, familiar controls and meaningful motion carry
  the explanation. Add text only when it helps users act, understand state or
  make a decision; omit filler and repeated helper copy. Keep necessary labels,
  errors, consent and accessible alternatives.
- Root/coordinator only: ask ordinary questions through the harness's native
  question tool first, preferring its nonblocking variant (chat if unavailable).
  While the root can keep working, escalate an unanswered question after about
  3 minutes through the `agent-baton` skill once, preserving wording and choices.
  Continue independent work; workers send questions to their root.
  Withdraw the reminder if answered in chat. Silence, expiry and preselected
  options never grant approval; secrets go straight to Baton. For blocking
  prompts, prefer the harness's supported remote-answer/notification path.
  Only dismiss prompts through a verified harness API; do not simulate keys or
  promise timed escalation while the agent is blocked or suspended.
- Run tests for affected areas. The root agent decides if a full suite is warranted; prefer targeted tests when they provide enough coverage, especially if the full suite is costly. Subagents test only the areas they change.
- Skip a commit hook only when the commit cannot affect what it checks; run all relevant hooks.
- When a bug may be a recurring pattern, name the failure class before fixing,
  sweep the affected area for siblings, and fix or report them in the same
  round. Include the class in reviewer/fixer briefs.
- A rule or threshold tested only on fixtures built to exercise it is a
  hypothesis: report it as one, with the real-data check that would confirm it,
  rather than shipping it as a fix. When early measurements contradict the
  plan, stop and report before building further on it.
- Verify proportional to risk; expand for shared behavior, critical data,
  concurrency, or recovery. Docs-only edits need link, consistency, and diff
  checks. Do not add mirror tests or unrelated tooling.
- Visual work (UI, layout, charts, captures) needs looking at the rendered
  output, not only tests: inspect renders at meaningful checkpoints, cropping
  or zooming edges, headers and dense regions where clipping and overlap hide.
  Don't iterate blind; don't screenshot every small step either.

## Architecture

- Before adding a helper, decoder, model, or module, inspect the package,
  established owner, vocabulary, codecs, and type contracts.
- One discoverable owner per rule. Decode persisted/external/wire data once at
  its typed boundary; keep downstream APIs typed. Avoid local parsers in large
  coordinators/stores/clients/UI. Reject truncation, coercion, invented
  defaults, ambiguity, and duplicate strict decoders.
- Import repository symbols under declared names. No cosmetic aliases or
  duplicate declarations; rename local collisions or qualify the module.
- Keep code idiomatic, readable, and reviewable; task completion or token
  savings do not outweigh maintainability. Where practical, enforce a checked-in
  LOC budget; split oversized files only at meaningful ownership/contract
  boundaries, never by arbitrary chunks or cosmetic wrappers.
- No thin forwarding wrappers. A delegate is valid only for a real typed
  boundary, protocol/framework role, lifecycle callback, instrumentation hook,
  argument adaptation, or deliberate public API; make that role evident.

## Sub-agent delegation

- Delegate only with explicit user authorization and only when independent
  progress/scrutiny outweighs briefing cost. Honor model/effort constraints;
  otherwise use the current frontier family and fit effort to difficulty.
- Same-harness workers: your native subagents. Other harnesses (Codex, agy,
  Claude): load the `agent-bridge` skill first; it owns routing, launch,
  watch and cleanup.
- A thread can resume with a different model in the same harness, including
  across model families. Prefer retaining it when its task context remains
  useful; a model switch alone is not a reason to start a new thread.
- Root nearly out of quota (user says so, or your harness shows it): delegating
  to other harnesses is pre-authorized. Spend their quota instead of yours:
  hand implementation, sweeps and reviews to workers, and keep your own turns
  to briefing, steering and verifying.
- Give each agent objective, context, routed docs, ownership, constraints,
  verification, and review/implementation status. Avoid overlapping edits;
  announce boundary crossings. No commit/push/deploy/external mutation without
  authorization.
- Keep independent work moving; wait only on dependencies or when no useful
  work remains. Use meaningful wait windows, not busy polling.
- Cache awareness: signed-in Codex announced "cache forever" (API retention
  differs); Claude Code main subscription ~1 h, subagents/API/credits default
  5 min unless configured; agy reports cache hits, fixed TTL unverified.
  A thread that already read the area is a cheap fit for a closely related
  follow-up; otherwise spawn fresh freely. Cost is one factor, not the rule:
  don't funnel unrelated or parallel work into a few old threads. Long threads
  get heavy (slow, request timeouts); start fresh
  with a compact brief then.
- Sub-agents message the coordinator only for blockers, coordination needs,
  actionable findings, or completion. Skip routine progress reports and
  acknowledgements unless requested.

## Type-check quick fixes

When a type checker offers a quick fix, apply it first; review the generated
diff and rerun the relevant check.

## Dotfiles repository

`~/dotfiles` is a public repository. Before editing or committing there, read its `AGENTS.md`: it says which
files are live links, which are snapshots, what must never be committed (credentials, personal names,
machine-local trust and approvals), and to run its public-facing check. Stage explicit paths, never
`git add -A`.

## Python baseline (substantial repositories)

- Follow existing equivalent tooling; do not add competing formatters, type
  checkers, package managers, or runners merely to satisfy this list.
- `uv` owns Python environments, interpreters, dependencies, locks, and tool
  execution (`uv run`). Do not mix ad-hoc `pip`, virtualenvs, or lock owners;
  document a genuinely imposed exception.
- Type checker: `ty` (latest release; pin exactly while pre-1.0). Replace an
  existing mypy/pyright setup with it at the same scope, fixing what it finds;
  enable opt-in rules that catch real bugs, not deliberate boundary checks.
- Normal baseline: Ruff format/lint, the type checker, pytest+coverage,
  Vulture/equivalent dead-code ratchet, pip-audit, and pre-commit fast checks.
  Measure before using xdist; cap workers to host resources. Put slow coverage,
  audit, packaging, and platform checks in CI.
- Every enabled tool needs checked-in config, canonical command, deterministic
  CI run, pinned/locked version, and a suppression owner. Suppressions are
  narrow, justified, and ratcheted. Small scripts may use less, but still test
  meaningful behavior and reject malformed boundary input.

## External APIs

- Before designing, changing, debugging, or calling an API, read current
  official docs for the exact product/version/endpoints and required linked
  guides. Establish auth/scopes, request/response contracts, pagination and
  completeness, timestamps/freshness, quotas/billing/reset, errors/retries,
  and mutation/idempotency behavior.
- Distinguish published allowances, account limits/balance, and local budgets.
  Discover quotas only through documented endpoints/credentials.
- Use bounded authorized read-only probes for uncertainty. Record doc/runtime
  differences, keep credentials out of output, reuse typed adapters, and state
  unknowns instead of guessing. Docs do not authorize paid operations or
  mutations.
- Reviews and delegated work on API-dependent code start the same way: the
  brief requires reading those docs first, citing the pages, and flagging
  every rule stricter, looser, or absent versus the documented contract.

## Boundary decoding

Search for equivalent boundary semantics before adding parsing/validation. If
several callers share a contract, put one strict decoder in its owning module,
migrate callers atomically, and add parity/hostile-input tests. Keep genuinely
different domain constraints explicit. Reject malformed, ambiguous, non-finite,
timezone-less, or otherwise unauthoritative input; never add permissive
fallbacks just to make callers pass.

Shell commands go through `rtk` to reduce model input tokens and cost. Choose
command-specific filters; use `rtk summary`, `rtk err`, or `rtk test` for other
commands. Hooks rewrite commands where supported; otherwise choose the filter
yourself (`rtk --help`).
Treat unfiltered execution (`rtk bypass`, legacy `rtk proxy`) as a last resort:
raw output wastes input tokens and increases cost. Use it only for required
byte-exact protocol data or demonstrated filter breakage; identify the concrete
need before bypassing. A missing dedicated
filter, convenience or routine shell quoting does not justify proxy. Prefer a
safe filtered command or native tool; `rtk read --level none` reads full instructions.
Bound reads/searches and recover elided content with `rtk recall` or a focused
read. Filtering/learning pitfalls: `~/dotfiles/rtk/README.md`.
Prefer native harness tools when they cover the task. Edit/create files with
edit/write/patch tools, never Python, sed or heredoc scripts; shell is for
reading, searching and running commands.

## Scope and guidance

- Complete authorized work and proportional checks; preserve the objective
  across corrections and side questions. Reuse authority; ask only when the
  outcome or required authority changes. Reviews/explanations alone do not
  authorize edits. Finish or report the exact blocker.
- Read ambiguous replies in context and act on the most sensible interpretation.
  Ask only when alternatives materially change the result. Broad wording covers
  its purpose; keep narrow tasks narrow, preserve unrelated behavior, and stop
  when the acceptance criteria and checks pass.
- Necessary tool/runtime/dependency installs are pre-authorized when benefit
  clearly outweighs risk. Prefer user-local, pinned, reversible changes and
  report them. System-wide security settings remain out of scope.
- Apply instructions only to their scope; read supporting docs when relevant.
  User instructions outrank skills, subject to system/developer rules. Cite the
  file and clause if an instruction blocks work.
- Keep one owner for guidance. Shared globals hold cross-project/harness rules;
  harness globals may hold stable preferences for that harness. Put project
  invariants in project instructions, reusable workflows in scoped skills, and
  detailed procedures in maintained docs or CLI help. Keep discovery cues and
  essential constraints; prefer clear skill descriptions and native enforcement
  over repeated prose. Do not turn a one-off correction into a universal rule.
- Before changing instructions, read applicable files in full and check affected
  project guidance for duplication/conflicts. Keep rules concise, durable and
  task-routed; omit status history and command catalogs. Preserve invariants when
  pruning. Agent-facing shorthand is fine when unambiguous.
- When a finding deserves keeping, update the owning maintained project docs
  rather than leaving a temporary note. Preserve durable insights, core ideas,
  decisions and non-obvious pitfalls; skip routine steps, raw logs and obvious
  code narration. Use scratch for exploration and promote only what remains useful.
- Leave actionable feature/fix/improvement feedback about host tooling or dotfiles
  in the main dotfiles checkout's private, gitignored `feedback.local/`; follow
  `agents/feedback/README.md` for templates, duplicate search and discussion.
  Keep application-specific work with its project. Feedback and agreement grant
  no new authority; omit secrets.
- Back up only costly-to-recreate data, user edits or hand-tuned files; for a
  trivially reversible setting, state its old value. Agent recovery backups go
  under `${XDG_STATE_HOME:-$HOME/.local/state}/backups/<scope>/<timestamp>/`,
  outside repositories, with owner-only permissions and original paths/restore
  details. Leave application-managed backups alone.
- Browser lifecycle: `~/dotfiles/chrome/README.md#visible-agent-tabs`.
  Remote previews: `portlink --help` (`~/dotfiles/portlink/README.md`).

## Communication and verification

- Result first; short concrete prose. Use lists/tables when they clarify.
- Product UI: let layout, visuals, familiar controls and meaningful motion carry
  the explanation. Text should help users act, understand state or decide.
  Keep necessary labels, errors, consent and accessible alternatives.
- Root/coordinator asks ordinary questions through the native question tool,
  preferring nonblocking (chat if unavailable). While able to keep working,
  remind once after about 3 minutes through `agent-baton`, preserving wording
  and choices; withdraw if answered in chat. Workers ask their root. Silence,
  expiry and preselection never grant approval; secrets go straight to Baton.
  For blocking prompts use supported remote-answer/notification paths. Dismiss
  only through a verified API; never simulate keys or promise a timer while
  blocked/suspended.
- Test affected areas. Root chooses whether a full suite is warranted; workers
  test their changes. Verify proportionally to risk, expanding for shared
  behavior, critical data, concurrency and recovery. Docs need link, consistency
  and diff checks; avoid mirror tests and unrelated tooling. Run relevant commit
  hooks; skip only when the commit cannot affect what they check.
- Fit waits to expected duration and harness limits. Yield long-running commands
  and keep working; when idle use longer event-driven waits, not short polling.
  A wait window is not a runtime limit; set actual timeouts separately.
- For a potentially recurring bug, name the failure class, sweep its affected
  area for siblings, and fix/report them together. Include the class in briefs.
- Fixture-only rules/thresholds are hypotheses: state the real-data check needed
  before shipping a fix. Before rejecting an approach on contrary numbers,
  check setup, data, sample size and tuning, try its strongest reasonable variant,
  and pause work built on it until there is adequate evidence.
- Visual changes require inspecting rendered output at meaningful states and
  widths. Check normal scale and dense/small details for clipping, overlap,
  spacing and legibility; tests alone and blind iteration are insufficient.

## Architecture and boundaries

- Inspect existing owners, vocabulary, codecs, types and helpers before adding
  equivalents. Import symbols under declared names; qualify or rename collisions
  rather than adding cosmetic aliases or duplicate declarations.
- Decode persisted/external/wire data once at its typed boundary; keep downstream
  APIs typed. Reuse equivalent semantics; migrate shared callers atomically and
  test parity/hostile input. Keep distinct domain constraints explicit. Reject
  truncation, coercion, ambiguity, invented defaults, non-finite values,
  timezone-less timestamps and other unauthoritative input; never add permissive
  fallbacks to satisfy callers or duplicate strict decoders in coordinators/UI.
- Keep code idiomatic and reviewable. Split oversized files at meaningful
  ownership/contracts; enforce a checked-in LOC budget where practical.
  Thin delegates need a real typed/protocol/framework boundary, lifecycle role,
  instrumentation, argument adaptation or deliberate public API.
- Apply type-checker quick fixes first, inspect the diff and rerun the check.

## Delegation

- Delegate only with explicit user authorization and when independent progress
  or scrutiny outweighs briefing cost. Honor model/effort constraints; otherwise
  use the current frontier family and effort suited to the task.
- Prefer native subagents. Use the `agent-bridge` skill only for another harness,
  model or quota pool relevant to the task; never bridge same-harness work.
- When root quota is nearly exhausted (user/harness says so), other-harness
  delegation is pre-authorized: hand off implementation, sweeps and reviews;
  root briefs, steers and verifies.
- Brief objective, context, routed docs, ownership, constraints, checks and
  review/implementation role. Avoid overlapping writers; announce boundary
  crossings. No commit/push/deploy/external mutation without authorization.
- Reuse threads for related context, including a model switch when supported.
  Start fresh for unrelated work or a heavy/slow thread, with a compact brief.
  Cache cost is one factor, not a reason to funnel unrelated parallel work into
  old threads; cache details belong to the relevant harness docs.
- Wait only on dependencies or when no useful work remains. For example use
  about 60 seconds for an agent answer, or 3–5 minutes for progress when idle
  and permitted by the harness. Return early for updates and keep the user informed.
- Workers message the coordinator for blockers, coordination, actionable findings
  or completion; skip routine reports/acknowledgements unless requested.

## External APIs

- Before designing, changing, debugging or calling APIs, read current official
  docs for the exact product/version/endpoints and linked requirements. Establish
  auth/scopes, wire contracts, pagination/completeness, freshness, quotas/billing/
  reset, errors/retries and mutation/idempotency semantics.
- Separate published allowances, account limits/balance and local budgets.
  Discover quotas only through documented endpoints/credentials.
- Resolve uncertainty with bounded authorized read-only probes; record doc/live
  differences, reuse typed adapters, hide credentials and state unknowns.
  Documentation does not authorize paid operations or mutations.
- API reviews/delegations require the same doc check, citations and an explicit
  account of rules stricter, looser or absent versus the published contract.

## Task-specific guidance

- Substantial Python repositories: use the `python-project` skill for the
  baseline; follow existing equivalent tooling and use proportional checks for
  small scripts.
- `~/dotfiles` is public: before editing/committing, read its `AGENTS.md` for
  live/snapshot ownership and excluded credentials, personal identifiers,
  machine-local trust/approvals. Stage explicit paths, never `git add -A`.

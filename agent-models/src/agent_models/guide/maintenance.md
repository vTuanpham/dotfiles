# Maintaining the shared model reference

`model-guide check` reads document drift and review age as JSON without provider processes.
Add `--live` to explicitly query native inventory.
`model-guide stale --live` also caches inventory warnings for consumers. Missing or signed-out
providers do not establish that their models disappeared.

Read `model-guide read sources` before source review. Keep strengths, measurements
and effort advice in models.md; published tiers in subscriptions.md. Neither
document records local accounts or balances.

Each review covers the capability domains and source limits in sources.md, not
just the overall effort table. Keep a concise evidence matrix in models.md and
record coverage/gaps in the proposal notes even when nothing changes. Use the
latest release and its methodology; date changes to tasks, weights, judges and
harnesses invalidate cross-version comparisons. Missing results stay Unverified.
Review cost-performance frontiers per domain and candidate set, including the
marginal gain from more effort. Do not merge unlike scores or cost definitions.

`model-guide refresh --prepare` collects facts and computes per-suite cost frontiers
without an agent. Normal refresh includes preprocessing before the proposal worker.
Inspect unavailable sources, exact settings and methodology changes; preprocessing
is not completed source review. Search bounded evidence with
`model-guide benchmarks --domain design --query sonnet --limit 5 --brief`.
Inspect both quality and efficiency views; their frontiers use the matching
candidate set and keep execution harnesses separate. Omit `--brief` for JSON.
Local account/plan/quota hints come automatically from existing stores and native
status, not hardcoded plans. Confirm the selected session binding and billing mode
before treating them as eligibility. Unknown access remains unknown.

For a worker proposal, `model-guide refresh --force` uses an installed Bridge
only as its sandboxed worker launcher. The reference tool owns proposal storage,
validation, reports and review. No proposal applies automatically, including
one with no changes. Read the report, fetch cited sources and verify changed
claims; then use `model-guide refresh --apply --yes`, or `--discard`.

For direct edits, source-check the claims, retain unresolved Unverified markers,
inspect generated coverage (`model-guide models --backend BACKEND --json`),
update meaningful family/domain advice, and update Checked dates when facts
change. `model-guide refresh --record --yes` compares against the committed
baseline, validates both documents and records their hashes without editing text.
New/moved references need a committed baseline before this command can run.

Only apply/record advances models.lock. Both leave changes uncommitted. Concurrent
document edits invalidate a proposal. Model roles and effort advice stay under
root review; proposals cannot change the reviewed OpenCode zero-retention list
in agent_models.inventory. Reference maintenance never switches accounts, sets
model defaults or changes delegation permissions.

When publishing changed benchmark figures, regenerate their README assets from
the reviewed snapshot and inspect the render. `docs/tools/README.md` owns the
generators; `model_effort.py` derives plotted settings, values and dates from data.

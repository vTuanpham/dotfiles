# Maintaining the shared model reference

`model-guide check` reads document drift and review age as JSON without provider processes.
Add `--live` to explicitly query native inventory.
`model-guide stale --live` also caches inventory warnings for consumers. Missing or signed-out
providers do not establish that their models disappeared.

Read `model-guide read sources` before source review. Keep strengths, measurements
and effort advice in models.md; published tiers in subscriptions.md. Neither
document records local accounts or balances.

For a worker proposal, `model-guide refresh --force` uses an installed Bridge
only as its sandboxed worker launcher. The reference tool owns proposal storage,
validation, reports and review. No proposal applies automatically, including
one with no changes. Read the report, fetch cited sources and verify changed
claims; then use `model-guide refresh --apply --yes`, or `--discard`.

For direct edits, source-check the claims, retain unresolved Unverified markers,
document or explicitly omit every live ID, and update Checked dates when facts
change. `model-guide refresh --record --yes` compares against the committed
baseline, validates both documents and records their hashes without editing text.
New/moved references need a committed baseline before this command can run.

Only apply/record advances models.lock. Both leave changes uncommitted. Concurrent
document edits invalidate a proposal. Model roles and effort advice stay under
root review; proposals cannot change the reviewed OpenCode zero-retention list
in agent_models.inventory. Reference maintenance never switches accounts, sets
model defaults or changes delegation permissions.

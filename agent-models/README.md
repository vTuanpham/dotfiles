# agent-models

[← Packages](../README.md#packages) · **uv tool** · shared model references

```text
Main session ─┐
Delegation ───┼── model-guide ── reviewed references
Bridge ───────┘                     ↑
                          proposal → source review → apply
```

Model strengths, effort and published allowances have one owner, independent of
worker orchestration. The model-selection skill reads this reference on demand.

```sh
uv tool install --with-editable ./agent-accounts --editable ./agent-models
model-guide read models
model-guide models --backend codex
model-guide read subscriptions     # only for allowance/retention decisions
model-guide check                  # reference files only; no provider processes
model-guide check --live           # explicitly query native inventories
model-guide read maintenance
```

The daily `agent-models-reference.timer` checks drift; at most weekly it asks
an installed Bridge to run a sandboxed proposal worker. Bridge is an optional
execution route for proposals, not an import dependency. Reading, checking,
source review and recording direct edits work without it. No update applies
automatically. State belongs to `$AGENT_MODELS_HOME` or
`${XDG_STATE_HOME:-~/.local/state}/agent-models`; documents and review hashes live
in `src/agent_models/guide/`. Reference edits remain uncommitted.

Listings describe native CLI inventory, not entitlement or the models selectable
by a particular native subagent tool. Account caches are separate observations;
the current session's native controls remain authoritative. The reviewed OpenCode
privacy allowlist lives in inventory.py and is also consumed by Bridge.

This separation follows the useful distinction in
[T3 Code's provider constraints](https://github.com/pingdotgg/t3code/blob/main/docs/internals/providers.md):
shared orchestration does not own provider protocols or account lifecycle.
We reuse that boundary; no T3 runtime or additional provider server is installed.

Checks: `uv run pytest` and `uv run ruff check src tests`.

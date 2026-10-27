## Model strength (dated reference)
Checked 2026-10-27. `agent-bridge guide plans` remains the entry point for this generic model guide. A user or project instruction outranks this advice. Check available IDs with `agent-bridge models --backend X`; a listing does not prove included usage.

Read [the subscription guide](subscriptions.md) (`agent-bridge guide subscriptions`) only when the choice depends on a plan, allowance or retention policy. Use live commands for account state; this document records no account balances or subscriptions.

### Four separate things: do not infer one from another
1. **Class** is where a model sits in its vendor's lineup. It is a naming and positioning rank, not a score. This guide always says "class" for it; "tier" means a subscription level only.

| Class | Codex | Claude | Gemini |
|---|---|---|---|
| small | Luna | Haiku | Flash |
| mid | Terra | Sonnet | Unverified |
| high | Sol | Opus | Unverified |
| top | Astra | Fable | Argon |

   Matching Sol to Opus and Terra to Sonnet is a positioning convention; the Gemini placements are Unverified.
2. **Measured performance** is the benchmark table below. Class does not predict it: in this snapshot Opus 5.5 (class high) scores above Fable 5.1 (class top) at medium and up, Sonnet 5.5 max (56) beats Astra max (53), and Terra 6.1 max (48) equals Sol medium. Choose a model by its row in the table, not by its class.
3. **Effort** is a per-job setting that moves a model along its own row in the table: it changes score, cost and latency, and its effect differs by model (small models gain a lot from it, large ones flatten, see below). It is chosen per task and is independent of class and of the allowance; a high-class model at low effort can score below a lower-class model at high effort. Each backend accepts only some levels (`agent-bridge start --help`).
4. **Usage guidance** (how freely to spend a model) depends on the account's allowance, not on class, score or effort. The same model at the same effort is routine on a deep allowance and reserved on a thin one. The advice below is conditional on that; the [subscription guide](subscriptions.md) lists what each tier allows.

To choose a model, go in this order: pick the lowest class that can do the task, read its row in the table for the effort that reaches the score you need and its cost, then check the allowance before spending (live quota, then the subscription guide). Moving up a class is justified by a better row in the table, not by the class name.

### Effort and model strength
Artificial Analysis Intelligence Index and average API cost per task (general reasoning, not coding-specific; dollars are API prices, not plan quota, so read them as relative cost). Sources: [model leaderboard](https://artificialanalysis.ai/leaderboards/models), [Coding Agent Index](https://artificialanalysis.ai/agents/coding-agents) (harness plus model). Each cell is index / $ per task. These are the existing benchmark snapshot, not new measurements.

| Model | low | medium | high | xhigh | max |
|---|---|---|---|---|---|
| Luna | 22 / $0.0045 | 30 / $0.02 | 33 / $0.03 | 35 / $0.04 | 38 / $0.07 |
| Haiku 5.5 | 29 / $0.02 | 34 / $0.05 | 38 / $0.08 | 41 / $0.12 | 43 / $0.21 |
| Sol | 42 / $0.13 | 48 / $0.21 | 50 / $0.32 | 51 / $0.39 | 52 / $0.72 |
| Sonnet 5.5 | 36 / $0.35 | 41 / $0.48 | 47 / $0.88 | 52 / $2.01 | 56 / $5.46 |
| Opus 5.5 | 42 / $0.55 | 51 / $1.34 | 54 / $1.82 | 56 / $3.46 | 58 / $5.98 |
| Astra | 46 / $0.82 | 50 / $1.54 | 51 / $1.73 | 52 / $2.31 | 53 / $3.26 |
| Fable 5.1 | 47 / $2.37 | 49 / $2.98 | 51 / $3.91 | 53 / $5.98 | 53 / $7.63 |
| Terra 5.6 | 27 / $0.14 | 30 / $0.18 | 34 / $0.34 | 38 / $0.63 | 42 / $1.40 |
| Terra 6.1 | 36 / $0.05 | 41 / $0.10 | 44 / $0.13 | 45 / $0.19 | 48 / $0.40 |

Others: Argon (Gemini 4, high) 53 / $1.62; Gemini 3.8 Flash high 41 / $3.49; DeepSeek V4.1 Flash max 45 / $0.26; GLM 5.3 max 45 / $2.01. Opus, Sonnet and Fable rows are "with fallback".
- **Small models need effort**: Luna gains 16 points from low to max for $0.0655 more.
- **Large models flatten**: Sol max adds 2 points over high for 2.3x the cost; Astra max adds 2 over high for 1.9x. `high` is the usual ceiling for a large model; `xhigh`/`max` pay only for audits and hard diagnosis. Opus and Sonnet are the exceptions, still gaining at xhigh and max.
- **A bigger class beats more effort within a family, not across families**: Sol medium (48, $0.21) outscores Luna max (38, $0.07), but Sonnet max (56) outscores Astra max (53). For the same ~50, Sol high costs $0.32, Opus medium $1.34, Astra medium $1.54.

### How to use each model (a starting point; override for the task)
Effort is limited to what each backend accepts (`agent-bridge start --help`). The top of a range is for audits or deep diagnosis. Small-model output always gets a spot-check. With a thin allowance, bound jobs and reserve expensive models; with a deep allowance or no short-window limit, repeat useful sweeps while checking weekly limits and live quota. [Subscriptions](subscriptions.md) maps published tiers to these conditions.

| Model | Role | Effort | Allowance-dependent advice |
|---|---|---|---|
| Luna | bulk implementation, sweeps, tests, first-pass audits | high to xhigh; max for audits | split into bounded jobs on thin allowances; repeat sweeps when the allowance is deep |
| Sol | tricky implementation, diagnosis, second-opinion review | medium to high; xhigh for hard diagnosis | step up when Luna struggles; serialize jobs when the allowance is thin |
| Terra 6.1 | fast visual, UI and computer-use work; writing | medium to high | compare Terra max (48, $0.40) against Sol medium (48, $0.21) for pure coding |
| Astra | hardest audits, architecture and read-only brainstorming | medium to high | avoid routine work on thin allowances; xhigh or max only if the user asks |
| Gemini 3.8 Flash (agy) | summaries, log triage, docs, mechanical sweeps | high | check the shared Gemini bucket before large fan-outs |
| Opus 4.6 Thinking (agy) | taste-heavy visual work, hard design review | medium to high | check the shared Claude/GPT bucket; benchmark strength Unverified |
| Sonnet 4.6 Thinking (agy) | mid-weight visual work | medium to high | check the same bucket; benchmark strength Unverified |
| Haiku 5.5 | cheap exploration, summaries, quick lookups | high | 38 at $0.08 in the snapshot; prefer bounded tasks |
| Sonnet 5.5 | UI/TUI/visual taste, live collaboration | medium to high | reserve capacity for iteration when the allowance is thin |
| Opus 5.5 | high-value design decisions | medium to high | reserve it when the allowance is thin |
| OpenCode free (zero-retention) | read-only exploration, summaries, mechanical edits | none | rotating availability; treat as small-model output and check retention in the subscription guide |

### Inventory coverage
The family-level advice above covers `gpt-6-luna`, `gpt-6-sol`, `gpt-6.1-sol`, `gpt-6-astra`, `gpt-6.1-terra`, `gemini-3.8-flash-low`, `gemini-3.8-flash-medium`, `gemini-3.8-flash-high`, `claude-opus-4-6-thinking`, `claude-sonnet-4-6`. This is model inventory, not subscription entitlement.

Intentionally omitted from individual benchmark rows: older `gpt-5.6-luna`, `gpt-5.6-sol`, `gpt-5.6-terra`; rotating free endpoints `opencode/beam-free`, `opencode/big-pickle`, `opencode/flint-40b-free`, `opencode/mimo-v2.6-flash-free`, `opencode/nemotron-3-ultra-free`, `opencode/nemotron-3.5-lightning-free`, `opencode/nemotron-3.5-super-vl-free`. Reasons: older families or no comparable effort benchmark; omission does not establish privacy or access. ZDR endpoint IDs are documented in [subscriptions](subscriptions.md). During a source review, add each new live ID to advice or this explicit omission list before recording the lock.

## Model strength (dated reference)
Checked 2026-10-30 for benchmarks and selection advice. Vendor positioning, token prices and OpenRouter speed below retain their 2026-10-27 observation date. Read with `model-guide read models` for model selection. User/project instructions outrank this advice. A listing does not prove included usage.

Read [the subscription guide](subscriptions.md) (`model-guide read subscriptions`) only when the choice depends on a plan, allowance or retention policy. Use live commands for account state; this document records no account balances or subscriptions.

### Four separate things: do not infer one from another
1. **Class** is where a model sits in its vendor's lineup. It is a naming and positioning rank, not a score. This guide always says "class" for it; "tier" means a subscription level only.

| Class | Codex | Claude | Gemini |
|---|---|---|---|
| small | Luna | Haiku | Flash |
| mid | Terra | Sonnet | Unverified |
| high | Sol | Opus | Unverified |
| top | Astra | Fable | Argon |

   Matching Sol to Opus and Terra to Sonnet is a positioning convention; the Gemini placements are Unverified.
2. **Measured performance** depends on the domain, benchmark version and execution setup. Overall indices help shortlist; a model can lead at coding and trail at research or design. Read the capability evidence below before choosing for a task. Class names do not establish performance.
3. **Effort** is a per-job setting that moves a model along its own row in the table: it changes score, cost and latency, and its effect differs by model (small models gain a lot from it, large ones flatten, see below). It is chosen per task and is independent of class and of the allowance; a high-class model at low effort can score below a lower-class model at high effort. Each backend accepts only some levels (the selected native tool or execution backend's help).
4. **Usage guidance** (how freely to spend a model) depends on the account's allowance, not on class, score or effort. The same model at the same effort can be used freely on a deep allowance and needs more care with job size and count on a thin one. The advice below is conditional on that; the [subscription guide](subscriptions.md) lists what each tier allows.

Choose in this order: establish the target session's account, included access/billing mode, selectable model/effort, tools, modalities and context; compare the task's domain evidence and reliability; then weigh quality against completion time, cost and remaining allowance. Shortlist two or three suitable options. Local profile/cache observations are useful hints; they do not prove an already-running session uses that account. Optional paid access is separate from included allowance and authorization to spend. See [subscriptions](subscriptions.md).

### Effort and model strength
Artificial Analysis **Intelligence Index v5.0**, retrieved 2026-10-30: broad capability composite / weighted average API USD per task. Source: [current model leaderboard](https://artificialanalysis.ai/leaderboards/models). The [v5 methodology](https://artificialanalysis.ai/methodology/intelligence-benchmarking) weights knowledge work, coding, science and general capability equally; it includes FrontierCode 2.0 and Terminal-Bench 4.0. Older unversioned scores were replaced, not treated as model regressions. Missing effort cells stay Unverified; never substitute an older release or non-reasoning setting.

| Model | Published effort: index / USD per task |
|---|---|
| Luna | low: 10 / $0.01; high: 21 / $0.07; xhigh: 23 / $0.10; max: 28 / $0.15 |
| Haiku 5.5 | high: 30 / $0.16; xhigh: 34 / $0.25; max: 36 / $0.41 |
| Sol 6.1 | medium: 46 / $0.36; high: 50 / $0.59; max: 55 / $1.27 |
| Sonnet 5.5 | medium: 30 / $0.78; high: 41 / $1.64; max: 54 / $10.02 |
| Opus 5.5 | medium: 48 / $2.45; high: 52 / $3.46; max: 58 / $10.04 |
| Astra | low: 43 / $1.42; medium: 51 / $2.73; high: 55 / $3.24 |
| Fable 5.1 | medium: 43 / $5.56; xhigh: 50 / $10.85; max: 49 / $12.99 |
| Terra 6.1 | medium: 38 / $0.17; high: 42 / $0.26; max: 51 / $0.96 |
| Gemini 4 Carbon | high: 59 / $7.76 |
| Gemini 4 Argon | high: 50 / $7.68 |

These are selected measurements; query `model-guide benchmarks --query MODEL` for all observed settings and their time/cost tradeoffs. Omission is not a ban or unsupported level. A model with only high has one entry; no xhigh/max cells are fabricated. Preprocessing derives settings from source rows; the target harness's catalog establishes selectable levels.

Others: Gemini 4 Carbon high 59 / $7.76; Argon high 50 / $7.68; Gemini 3.8 Flash high 31 / $7.77; DeepSeek V4.1 Flash 1017 max 32 / $0.60; GLM 5.3 max 32 / $5.01. Opus, Sonnet and Fable rows explicitly use the source's **with fallback** configuration, not an isolated model.
- **Small models need effort**: compensate for lower capability with more reasoning. For models exposing high/xhigh/max, these suit simple/routine/harder worker tasks respectively. This is a model-specific example, not a shared range: use the actual catalog and measured curve. Low/medium remain allowed but are usually less attractive small-worker starting points. Larger-model quality is not guaranteed by extra effort.
- **Large models flatten**: start larger models at low/medium or task-appropriate high. Raise effort for demonstrated difficulty or worthwhile measured gains, not as a universal default. The curve can be non-monotonic; a more expensive setting need not improve the observed score.
- **A bigger class beats more effort within a family, not across families**: treat this as a hypothesis to check in the relevant domain, not a selection rule. Neither model size nor effort guarantees the better result.

### Capability evidence

Use separate domain profiles; never average unlike benchmark scales. Current releases and access recipes are in [sources](sources.md). Retrieval date is 2026-10-30; publication dates below remain the sources' own dates.

**LiveBench 2.0, release 2026-10-25**: [published suites](https://livebench.ai/#/) ([release CSV](https://livebench.ai/data/20261025/table.csv)). Settings: max for these rows. One run per suite; design, research and reasoning use different grading from deterministic coding/browser tasks. Overall weights: long agentic ×2, coding/design ×1.5, other suites ×1. Check the current [methodology](https://livebench.ai/#/methodology); the old LiveBench 1.0 categories are not the current profile.

| Model | Long agentic | Design | Coding | Browser | Data analysis | Research | Reasoning |
|---|---:|---:|---:|---:|---:|---:|---:|
| Fable 5.1 | 77.9 | 83.4 | 97.7 | 89.8 | 80.3 | 82.0 | 91.7 |
| Astra | 77.5 | 82.0 | 93.7 | 91.3 | 83.0 | 85.2 | 92.7 |
| Opus 5.5 | 72.8 | 86.9 | 96.3 | 88.4 | 80.3 | 85.0 | 92.2 |
| Sol 6.1 | 68.7 | 82.1 | 96.0 | 93.3 | 82.7 | 83.5 | 92.6 |
| Sonnet 5.5 | 63.4 | 85.0 | 94.7 | 89.3 | 59.5 | 83.6 | 91.6 |
| Terra 6.1 | 48.6 | 82.3 | 94.3 | 93.1 | 82.3 | 73.9 | 88.7 |

**Arena category evidence** from the [official feed](https://huggingface.co/datasets/lmarena-ai/leaderboard-dataset): human preference is distinct from verified correctness. WebDev, published 2026-10-28: Opus 5.5 max 1810±13 (3,473 votes), Astra max 1773±10 (7,210), Sonnet 5.5 xhigh 1770±11 (4,469), Sol 6.1 max 1751±11 (4,092). Astra and Sonnet's intervals overlap; this does not establish a decisive winner. Style-controlled Vision, 2026-10-19: Sol 6.1 max 1294±13 and Astra max 1285±10 also overlap. Agent, 2026-10-28, reports observed net improvement and behavior signals, not a controlled task pass rate. Preprocessing uses style-controlled Text/Vision/Document and preserves each board's publication date; Search and WebDev retain their named source configurations.

**Vals Index 2.2**, updated 2026-10-29: [GDP-weighted finance/coding/legal/tax evaluation](https://www.vals.ai/benchmarks/vals_index). Default-run effort is not labelled in the main table; do not equate it to the max-effort rows above. Sonnet 5.5 leads overall (70.85%), but Opus 5.5 leads Sonnet on Terminal-Bench 4.0 (65.15% vs 64.14%) while Sonnet leads on Code Migration v1.1 (87.4% vs 80.5%). That reversal is why the components matter. The index uses a subset of migration tasks; retain that scope. [Terminal-Bench 4.0](https://www.vals.ai/benchmarks/terminal-bench-4) uses mini-swe-agent, 66 tasks, three pass@1 runs and an eight-hour per-task limit; its scores are not comparable to 2.1.

| Domain | Additional current evidence | Coverage limit |
|---|---|---|
| Repository fixes / understanding | [AA Coding Agent Index v2.0](https://artificialanalysis.ai/agents/coding-agents), [SWE-bench](https://www.swebench.com/) | Model plus harness; v2.0 still uses FrontierCode v1.1, unlike the general index's 2.0. Public AA numeric chart data Unverified here. |
| Reasoning / math / science | AA v5 HLE-Diamond, CritPt v2 hard subset, Terminal-Bench-Science 0.1 | Domain-level model ranking Unverified where component values are unavailable; overall is not a math score. |
| Writing / instruction following / languages | Arena Text category filters; AA IFBench and multilingual evaluations | Preference/style and objective instruction compliance differ; no inference from English overall to other languages. |
| Vision / documents | Arena Vision/Document, AA MMMU-Pro and GDP.pdf | Reading images does not establish computer-use ability; newer model/effort coverage can be absent. |
| Long context | [LongBench v2](https://longbench2.github.io/) | Latest verified family version here; board mostly covers older models. Current-family comparisons Unverified; context-window size is not retrieval quality. |
| Tool calling | [BFCL V4](https://gorilla.cs.berkeley.edu/leaderboard.html) | Latest published board found, dated 2026-04-12; current-family coverage Unverified. Native function calling and prompted calling differ. |
| Computer use / long horizon | [OSWorld 2.0](https://osworld-v2.xlang.ai/) | Released 2026-06-26; full/partial completion and step budgets differ. Current-family comparisons Unverified; no carryover from OSWorld 1.x. |

### Cost versus performance

Compare frontiers within one source/release/domain and exact effort/harness. Keep API spend, included allowance, optional paid credits, response latency and agent completion time separate. Higher effort changes quality, token use and time together; inspect measured combinations rather than assuming a smooth or monotonic curve.

Derived from the current [LiveBench cost CSV](https://livebench.ai/data/20261025/cost.csv) and release weights, among the six max-effort rows above: Terra → Sol → Opus → Astra → Fable are the observed overall cost/quality frontier. Sonnet is dominated on that aggregate, yet remains on the design frontier. Frontier membership is not statistical significance or a universal recommendation. Sol's overall proxy is 84.1 at about $0.761/success; Opus 85.1 at about $4.290, Astra 85.6 at $4.548, Fable 85.7 at $6.904. This proxy divides mean task spend by weighted overall score; it is not a guaranteed retry cost. LiveBench publishes no per-task duration in these CSVs.

**Time-aware comparison**, from [Vals 2.2](https://www.vals.ai/benchmarks/vals_index), 2026-10-29, using the source's default-run labels:

| Model | Vals overall | USD / Test | Duration / Test |
|---|---:|---:|---:|
| Luna | 52.32% | $0.45 | 32m23s |
| Terra 6.1 | 60.47% | $2.92 | 39m35s |
| Sol 6.1 | 63.94% | $3.61 | 44m24s |
| Sonnet 5.5 | 70.85% | $18.70 | 1h26m |
| Opus 5.5 | 70.18% | $28.12 | 1h25m |
| Astra | 65.02% | $21.28 | 33m39s |

For these rows, Astra can trade extra spend for lower observed completion time than Sol; that is not a latency guarantee for another task. The Vals and LiveBench costs have different definitions and must not be merged. `model-guide benchmarks` returns source dates, exact labels, available time columns and measured effort tradeoffs; missing time stays unknown.

### What vendors advertise (claims, not measurements)
Last checked 2026-10-27. Vendor speed is the vendor's own relative rating. Measured speed is OpenRouter's median output tokens per second and median latency over a 30-minute window on that date, request-weighted across providers (load-dependent, not task completion time). Prices are list USD per million input / output tokens. Sources: [OpenAI models](https://learn.chatgpt.com/docs/models.md), [Anthropic models overview](https://docs.anthropic.com/en/docs/about-claude/models/overview), [OpenRouter models](https://openrouter.ai/api/v1/models).

| Model | Vendor positioning | Vendor speed | Measured (OpenRouter) | Price in / out |
|---|---|---|---|---|
| Luna | most efficient; focused high-volume tasks: summarization, extraction, focused coding (capability 3 of 5 icons) | 4 icons | 67 tok/s, 2.4 s | $0.10 / $0.50 |
| Terra 6.1 | fast, efficient; writing, visual understanding, computer use (capability 5 icons) | 4 icons | 75 tok/s, 2.1 s | $1 / $5 |
| Sol 6.1 | near-Astra performance at lower cost; repeated, long-running work (capability 5 icons) | 3 icons | 49 tok/s, 5.6 s | $2 / $10 |
| Astra | most capable; hardest work across code, apps and research (capability 5 icons) | 2 icons | 43 tok/s, 7.0 s | $10 / $50 |
| Haiku 5.5 | high-volume, latency-sensitive: classification, extraction, routing | fastest | 144 tok/s, 1.2 s | $0.10 / $0.50 |
| Sonnet 5.5 | best combination of speed and intelligence | fast | 105 tok/s, 2.2 s | $2 / $10 |
| Opus 5.5 | start here for most workloads; long-running agentic coding and knowledge work | moderate | 78 tok/s, 3.7 s | $4 / $20 |
| Fable 5.1 | demanding reasoning and long-horizon agentic work, or when Opus at higher effort still falls short | slower | 67 tok/s, 3.0 s | $10 / $50 |

OpenAI's icon counts have no stated maximum; compare them only with each other. Advertised capability and token throughput do not establish domain superiority or task completion speed. OpenAI's dated guidance starts Astra at its lightest setting and Luna at High; the local Luna worker preference below deliberately spends more effort for harder work.

### How to use each model (a starting point; override for the task)
Effort is limited to what each backend accepts (the selected native tool or execution backend's help). The top of a range is for audits or deep diagnosis. Small-model output always gets a spot-check. With a thin allowance, keep jobs small and spend the expensive models where they matter most; with a deep allowance or no short-window limit, repeat useful sweeps while checking weekly limits and live quota. [Subscriptions](subscriptions.md) maps published tiers to these conditions.

| Model | Role | Effort | Allowance-dependent advice |
|---|---|---|---|
| Luna | bulk implementation, sweeps, tests, first-pass audits | follow the small-worker effort guidance above | split into bounded jobs on thin allowances; repeat sweeps when the allowance is deep |
| Sol | tricky implementation, diagnosis, second-opinion review | medium to high; xhigh for hard diagnosis | step up when Luna struggles; serialize jobs when the allowance is thin |
| Terra 6.1 | fast visual, UI and computer-use work; writing | medium to high | inspect domain results and success cost; token throughput alone does not establish faster completion |
| Astra | hardest audits, architecture and read-only brainstorming | low to medium; high for the hardest tasks | step up effort when justified; check domain quality, completion time and cost before xhigh/max |
| Fable 5.1 | demanding reasoning and long-horizon agentic work; when the domain evidence warrants it | medium to high | verify included plan access versus paid credits, then compare long-horizon quality and cost |
| Gemini 3.8 Flash (agy) | summaries, log triage, docs, mechanical sweeps | high | check the shared Gemini bucket before large fan-outs |
| Opus 4.6 Thinking (agy) | taste-heavy visual work, hard design review | medium to high | check the shared Claude/GPT bucket; benchmark strength Unverified |
| Sonnet 4.6 Thinking (agy) | mid-weight visual work | medium to high | check the same bucket; benchmark strength Unverified |
| Haiku 5.5 | cheap exploration, summaries, quick lookups | follow the small-worker effort guidance above | prefer bounded tasks and verify the domain; small-model efficiency is not uniform |
| Sonnet 5.5 | UI/TUI/visual taste, live collaboration | medium to high | keep some capacity for iteration when the allowance is thin |
| Opus 5.5 | the vendor's default start for most workloads; long-running agentic coding, high-value design decisions | medium to high | on a thin allowance, pick the tasks where it matters most |
| OpenCode free (zero-retention) | read-only exploration, summaries, mechanical edits | use the endpoint's exposed settings | rotating availability; treat as small-model output and check retention in the subscription guide |

### Inventory coverage
`model-guide models --backend BACKEND --json` generates coverage from the current
native inventory and cached benchmark evidence: resolved identities, exposed
efforts, matching sources/settings and models without an exact benchmark match.
No handwritten omission list is maintained. Unmatched models are unmeasured,
not deprecated, forbidden or equivalent to a nearby family/version. Native CLI
inventory is not session entitlement; the target worker tool can expose a smaller set.

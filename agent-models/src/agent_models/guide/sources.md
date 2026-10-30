## Where the reference facts come from (first-hand access notes)
Benchmark sources checked 2026-10-30; vendor/plan recipes below retain their 2026-10-27 review unless separately dated. Use the current release and methodology, not cached snippets or an older project README. Record fetch failures rather than substituting an older benchmark. Sources never establish the selected session's account state.

### Capability coverage and current releases

| Primary source | Current version/release checked | Use and limits |
|---|---|---|
| [Artificial Analysis models](https://artificialanalysis.ai/leaderboards/models) / [method](https://artificialanalysis.ai/methodology/intelligence-benchmarking) | Intelligence Index v5.0, announced 2026-10-27 | Overall plus domain evaluations; exact model/effort/configuration, weighted task cost and response timing. v4 scores are incomparable. |
| [AA coding agents](https://artificialanalysis.ai/agents/coding-agents) / [method](https://artificialanalysis.ai/methodology/coding-agents-benchmarking) | Coding Agent Index v2.0 | FrontierCode v1.1, Terminal-Bench 4.0, SWE-Atlas-QnA-AA; its FrontierCode version differs from the general index's 2.0. Numeric charts were unavailable to the plain reader. |
| [Arena](https://arena.ai/leaderboard) / [method](https://arena.ai/how-it-works) / [official dataset](https://huggingface.co/datasets/lmarena-ai/leaderboard-dataset) | Dynamic, modality-specific publication dates | Text categories, WebDev, Vision, Document, Search and Agent. Preserve effort, counts, confidence intervals, adjustment filters and preliminary status. Preference differs from correctness; Agent uses a different scale. |
| [LiveBench](https://livebench.ai/#/) / [method](https://livebench.ai/#/methodology) | 2.0, release 2026-10-25 | Long agentic, design, coding, browser, data analysis, research, reasoning; one run/suite. Read current CSVs, weights, costs and effort metadata. Old LiveBench 1.0 categories and repository/paper are not the 2.0 method. |
| [Vals Index](https://www.vals.ai/benchmarks/vals_index) / [method](https://www.vals.ai/methodology) | 2.2, board updated 2026-10-29 | GDP-weighted finance/coding/legal/tax; inspect component reversals and Code Migration's index subset. Keep Cost/Test and Duration/Test labels; unlabelled default effort is not max. |
| [Terminal-Bench](https://www.tbench.ai/) / [Vals run](https://www.vals.ai/benchmarks/terminal-bench-4) | 4.0 | Vals: mini-swe-agent, three pass@1 runs, 66 tasks, eight-hour task limit, duration/cost. Task/harness changes make 2.1 incomparable. |
| [SWE-bench](https://www.swebench.com/) / [harness](https://www.swebench.com/SWE-bench/reference/harness/) | Current Verified / Multilingual / Multimodal tracks | Repository repair; match track, harness and run date. Do not substitute a saturated board for a harder current evaluation. |
| [LiveCodeBench](https://livecodebench.github.io/) | Read current release/window from leaderboard | Algorithmic coding, self-repair, execution and test prediction; retain window and pass metric. Contest scores do not establish repository/UI ability. |
| [LongBench v2](https://longbench2.github.io/) | v2 | Long-context reasoning; CoT and length bins matter. Sparse current-family coverage; window size is not retrieval quality. |
| [BFCL](https://gorilla.cs.berkeley.edu/leaderboard.html) | V4, board dated 2026-04-12 | Function calling/multi-turn use; distinguish native from prompted calls. Current-family coverage may be absent. |
| [OSWorld](https://osworld-v2.xlang.ai/) | 2.0, announced 2026-06-26 | Long-horizon computer use; preserve full/partial reward, step budget and full/offline subset. Do not relabel 1.x results. |

Cover reasoning/math/science, repository/terminal work, UI/design, writing and instruction following, vision/documents, long context, tool use, research and professional/data work. Missing current evidence is Unverified, not zero. Compare cost-quality and completion-time frontiers within a source and domain; never merge unlike scores into a universal rating.

### Automatic preprocessing and rechecks

`model-guide refresh --prepare` runs no model: public data, provenance and calculated cost frontiers go into private tool state. Normal refresh runs it before the worker. `model-guide benchmarks --backend BACKEND --domain DOMAIN --query MODEL --limit 5` matches bounded evidence to the native inventory and automatically observed local account/plan/quota hints. Omit the backend for unrestricted benchmark search. It reports match counts, limits, dates, effort and available time/cost; full data remains in the snapshot. Neither command selects a model, changes defaults or switches accounts.

LiveBench releases come from site metadata, Arena uses its latest export, AA reads
the current methodology version, and Terminal-Bench follows the newest release
linked by Vals Index. Snapshot dates/settings remain attached to each source.

Query results retain separate quality and efficiency views. The efficiency
frontier is recalculated within the filtered candidate set, source and release;
Vals execution harnesses remain separate. Backend queries use coding/terminal
proxies, not a measured database/security/architecture score. `--brief` renders
compact evidence without removing confidence intervals or account freshness.

- LiveBench's HTML links its current frontend script; read its release catalog and effort metadata, never execute downloaded code. Fetch the release's table.csv, categories.json and cost.csv. Validate schemas, finite values, counts and weights. Cost/success is estimated; overall cost divided by weighted quality is a proxy, not a retry guarantee. Time is not published in those CSVs.
- Arena publishes a CC-BY-4.0 dataset through Hugging Face's documented [Parquet export API](https://huggingface.co/docs/dataset-viewer/parquet). Read the latest complete export shards in memory, retaining dates/digests. Different evaluations sharing a display name are preserved and flagged. The [commit history](https://huggingface.co/datasets/lmarena-ai/leaderboard-dataset/commits/main) shows regular batches around 03:00 UTC for the previous day's results. Use this official feed directly; no extra freshness approval is needed.
- Vals exposes headline/component HTML tables with cost/time; retain its version and definitions. No stable public API was established.
- AA exposes a server-rendered leaderboard and current methodology. Its [official free API](https://artificialanalysis.ai/api-reference) requires a user-created key, allows 1,000 requests/day and requires attribution. No key/account was created here. Legacy fields in API examples do not establish current-index membership. Measured effort deltas preserve fallback configuration; response latency is not agent completion time.
- Agents review missing sources and changed schemas/methodologies, recheck primary links and interpret recommendations. Preprocessing never proves subscription entitlement, authorizes paid calls or makes role changes automatically.

### Reached and useful
| Source | URL | What it gives | How to read it |
|---|---|---|---|
| OpenAI model guide | `https://learn.chatgpt.com/docs/models.md` | each model's one-line positioning (`description="..."`), a Capability and a Speed rating, surfaces and API availability, reasoning-effort advice | Fetch the `.md` form with curl (some web readers reject its `text/markdown` type). The ratings are icon lists, so count the entries after `title: "Capability"` and `title: "Speed"` for each `name="gpt-..."` block; the rendered HTML shows them only as JavaScript icons. The counts have no stated maximum: compare them only with each other. |
| OpenAI pricing | `https://learn.chatgpt.com/docs/pricing.md` | plan list, per-plan message estimates per five hours, credit rates per model, availability notes for new models | Read the tables by row name; tier names are the vendor's ("Pro" for the $100, $200 and $500 tiers, no multipliers published). |
| Anthropic model overview | `https://docs.anthropic.com/en/docs/about-claude/models/overview` | one-line positioning, "Comparative latency" row, list prices, model IDs, the "start with ..." recommendation | Server-rendered HTML: strip tags and read the text. The latency words (Slower, Moderate, Fast, Fastest) come in the same order as the model columns. |
| OpenRouter model page (measured speed) | `https://openrouter.ai/<vendor>/<slug>` (e.g. `openai/gpt-6.1-terra`) | per-provider 30-minute stats: median output tokens per second, median latency, request counts | Fetch with curl and a browser user agent, unescape `\"`, then regex each `"stats":{"endpoint_id":...,"p50_latency":ms,...,"p50_throughput":tokens_per_s,...,"throughput_request_count":n,...}` object. Drop endpoints with few requests and weight by `throughput_request_count`. A snapshot that varies by provider and load; it does not say how many tokens a task needs. |
| OpenRouter model list | `https://openrouter.ai/api/v1/models` | list price per token for every model and alias, context length, `:batch` variants at half price, `~vendor/name-latest` aliases | Public JSON, no key. Multiply `pricing.prompt` and `pricing.completion` by 1,000,000 for dollars per million tokens. Prices are OpenRouter's pass-through list prices. |
| Artificial Analysis leaderboard | `https://artificialanalysis.ai/leaderboards/models` | Current-index score, task cost and timing per model/effort | Read the HTML table with its methodology version. Preserve "with fallback"; response time is not agent duration. |
| OpenCode Zen and Go | `https://opencode.ai/docs/zen`, `https://opencode.ai/docs/go` | which provider models Zen routes, their prices; Go limits, retention and the models trained on (`*-contributor`) | HTML text; read the tables by model name. |
| Claude plans | `https://support.claude.com/en/articles/11145838` | Pro, Max 5x and Max 20x limits | Article text; it publishes no per-plan model list. |

### Reached but empty or not usable for this
- **OpenRouter public endpoints API** (`/api/v1/models/<vendor>/<slug>/endpoints`): provider list and uptime work, but `throughput_last_30m` and `latency_last_30m` are null without credentials. Read the model page instead (the OpenRouter model page row above).
- **Artificial Analysis speed**: the leaderboard HTML contains no output-speed or time-to-first-token fields. Take measured speed from OpenRouter's model pages and vendor ratings (labelled as claims).
- **Antigravity model page** (`https://antigravity.google/docs/models`): client-rendered; the fetched page has no model rows. Use `model-guide models --backend agy` for what an account can start, and `https://antigravity.google/pricing` and `/docs/plans` for plan facts.
- **OpenAI HTML model page**: ratings and some tables render in JavaScript; use the `.md` form.

### Rules for what a source may support
- Vendor ratings and positioning are claims. Label them "advertised" and keep them apart from benchmark rows and from measured numbers.
- A price on one site is not an allowance: dollars per token say nothing about plan quota.
- A model ID in a live list proves it can be started, not that a plan includes it.
- A number no fetched source confirms stays as it was or is marked Unverified.

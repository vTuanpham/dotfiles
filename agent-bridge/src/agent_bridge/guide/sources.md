## Where the reference facts come from (first-hand access notes)
Verified 2026-10-27 by fetching each source directly. Use this before a refresh so no time goes to dead ends. Reached means a plain `curl -sL` returned the data below; if a recipe stops working, say so in the refresh notes and fix this page. Nothing here is account state: live commands (`codex-auth list`, `agent-bridge quota`, `agent-bridge models --backend X`, `opencode models`) answer that.

### Reached and useful
| Source | URL | What it gives | How to read it |
|---|---|---|---|
| OpenAI model guide | `https://learn.chatgpt.com/docs/models.md` | each model's one-line positioning (`description="..."`), a Capability and a Speed rating, surfaces and API availability, reasoning-effort advice | Fetch the `.md` form with curl (some web readers reject its `text/markdown` type). The ratings are icon lists, so count the entries after `title: "Capability"` and `title: "Speed"` for each `name="gpt-..."` block; the rendered HTML shows them only as JavaScript icons. The counts have no stated maximum: compare them only with each other. |
| OpenAI pricing | `https://learn.chatgpt.com/docs/pricing.md` | plan list, per-plan message estimates per five hours, credit rates per model, availability notes for new models | Read the tables by row name; tier names are the vendor's ("Pro" for the $100, $200 and $500 tiers, no multipliers published). |
| Anthropic model overview | `https://docs.anthropic.com/en/docs/about-claude/models/overview` | one-line positioning, "Comparative latency" row, list prices, model IDs, the "start with ..." recommendation | Server-rendered HTML: strip tags and read the text. The latency words (Slower, Moderate, Fast, Fastest) come in the same order as the model columns. |
| OpenRouter model page (measured speed) | `https://openrouter.ai/<vendor>/<slug>` (e.g. `openai/gpt-6.1-terra`) | per-provider 30-minute stats: median output tokens per second, median latency, request counts | Fetch with curl and a browser user agent, unescape `\"`, then regex each `"stats":{"endpoint_id":...,"p50_latency":ms,...,"p50_throughput":tokens_per_s,...,"throughput_request_count":n,...}` object. Drop endpoints with few requests and weight by `throughput_request_count`. A snapshot that varies by provider and load; it does not say how many tokens a task needs. |
| OpenRouter model list | `https://openrouter.ai/api/v1/models` | list price per token for every model and alias, context length, `:batch` variants at half price, `~vendor/name-latest` aliases | Public JSON, no key. Multiply `pricing.prompt` and `pricing.completion` by 1,000,000 for dollars per million tokens. Prices are OpenRouter's pass-through list prices. |
| Artificial Analysis leaderboard | `https://artificialanalysis.ai/leaderboards/models` | Intelligence Index and cost per task for a row per model and effort | Large HTML page (about 2 MB). Cells are `index / $ per task`; Opus, Sonnet and Fable rows are "with fallback". |
| OpenCode Zen and Go | `https://opencode.ai/docs/zen`, `https://opencode.ai/docs/go` | which provider models Zen routes, their prices; Go limits, retention and the models trained on (`*-contributor`) | HTML text; read the tables by model name. |
| Claude plans | `https://support.claude.com/en/articles/11145838` | Pro, Max 5x and Max 20x limits | Article text; it publishes no per-plan model list. |

### Reached but empty or not usable for this
- **OpenRouter public endpoints API** (`/api/v1/models/<vendor>/<slug>/endpoints`): provider list and uptime work, but `throughput_last_30m` and `latency_last_30m` are null without credentials. Read the model page instead (the OpenRouter model page row above).
- **Artificial Analysis speed**: the leaderboard HTML contains no output-speed or time-to-first-token fields. Take measured speed from OpenRouter's model pages and vendor ratings (labelled as claims).
- **Antigravity model page** (`https://antigravity.google/docs/models`): client-rendered; the fetched page has no model rows. Use `agent-bridge models --backend agy` for what an account can start, and `https://antigravity.google/pricing` and `/docs/plans` for plan facts.
- **OpenAI HTML model page**: ratings and some tables render in JavaScript; use the `.md` form.

### Rules for what a source may support
- Vendor ratings and positioning are claims. Label them "advertised" and keep them apart from benchmark rows and from measured numbers.
- A price on one site is not an allowance: dollars per token say nothing about plan quota.
- A model ID in a live list proves it can be started, not that a plan includes it.
- A number no fetched source confirms stays as it was or is marked Unverified.

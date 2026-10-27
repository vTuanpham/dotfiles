## Subscriptions (vendor catalog, no account state)
Checked 2026-10-27. Read this only when the choice depends on a plan, allowance or retention policy. For strengths and effort advice, use [models](models.md) (`agent-bridge guide plans`). Prices are published USD prices; region, billing terms and rollout can differ. **Unverified** means the cited sources do not establish the detail; do not infer entitlement from a model listing.

### Find live account state
- `codex-auth list`: selected account and cached allowance; mask emails when reporting. Live output may label the $100 tier differently from the pricing page. Codex `/status` and the vendor usage dashboard show limits and reset times.
- `agent-bridge quota --backend agy`: refresh account buckets; `agent-bridge models --backend agy --account ACCOUNT`: account-specific IDs, effort, cost tiers and buckets.
- `agent-bridge models --backend X`: backend inventory, not proof of included usage. `opencode models` and OpenCode's console show provider access and billing. Claude's `/status` and model picker establish live access; the bridge lists aliases only.

### Codex / ChatGPT
The [pricing page](https://learn.chatgpt.com/docs/pricing) lists:

| Tier | Published access and allowance |
|---|---|
| Free ($0) | Luna, Standard speed, desktop app, subject to rollout; numeric allowance Unverified |
| Go ($8/month) | Same documented Luna access; numeric allowance Unverified |
| Plus ($20/month) | CLI, IDE, web and cloud integrations; Sol 6.1 and Luna named |
| Pro ($100/month) | Plus features; no five-hour limit; weekly limits may apply |
| Pro ($200/month) | Same published Pro row |
| Pro ($500/month) | Same row, plus Ultrafast access |
| Business | $20/seat/month annually (2+ seats), $25 monthly; Standard Business estimates match Plus |
| Enterprise / Edu | Flexible pricing uses credits without fixed rate limits; otherwise Plus-like per-seat limits for most features |
| API key | CLI/SDK/IDE, API model access and token billing; no cloud features; API limits apply |

The vendor publishes no multipliers between Pro tiers. Plus/Standard Business estimates per five hours: Astra 5–45, Sol 6.1 15–160, Terra 6.1 35–285, Sol 6 15–150, Luna 350–3000. These are estimates, with shared local/cloud usage and possible weekly limits. Astra is thin relative to Luna; no short-window limit does not mean unlimited weekly usage. Source: [pricing and usage](https://learn.chatgpt.com/docs/pricing).

Privacy/retention: [Codex security](https://learn.chatgpt.com/docs/security) describes data controls. Business data is not used for training by default ([pricing](https://learn.chatgpt.com/docs/pricing)). **Unverified** here: tier-specific retention durations and consumer training defaults; check the applicable data controls and API terms before sensitive work. API billing is separate from subscription allowances.

### Antigravity / agy
Published allowance classes from [pricing](https://antigravity.google/pricing) and [plans](https://antigravity.google/docs/plans):

| Tier | Published allowance |
|---|---|
| Individual / free ($0) | Basic weekly rate limits; unlimited Tab completions and Command requests |
| Google AI Plus | Included in the model-access table's Free/Plus column; separate allowance/price Unverified here |
| Google AI Pro | Higher quota refreshed every five hours until the weekly limit; flexible AI credit pool; numeric allowance Unverified |
| Google AI Ultra | Highest quota refreshed every five hours and highest weekly limits; flexible AI credit pool; numeric allowance Unverified |
| Business via Google Cloud | Consumption-priced API; eligible Gemini Enterprise Standard/Plus from $30/seat/month, or pay-as-you-go with $0 seat fee |

[Model availability](https://antigravity.google/docs/models): Gemini 3.8 Flash spans Free/Plus, Pro, Ultra and Enterprise. Argon is on paid Pro (or eligible device trials), Ultra and Enterprise. Claude 5.5 Sonnet/Opus Thinking requires non-trial Pro, Ultra or Enterprise. Claude 4.6 Sonnet/Opus Thinking is listed for Free/Plus and Pro, with removal scheduled November 2, 2026. Enterprise also lists Gemini 3.7 Flash, 3.6 Flash and 3.1 Pro. GPT-OSS is excluded by the bridge. Listing and rollout can differ: check live commands before launch.

Privacy/retention: individual access uses terms derived from Google Terms of Service; Business uses Google Cloud terms ([plans](https://antigravity.google/docs/plans)). **Unverified**: training defaults and retention durations for each tier. Do not treat unlimited completions as unlimited agent-model usage; inspect the live Gemini and Claude/GPT buckets.

### OpenCode
OpenCode can also use external providers; their billing and data terms are separate.

- **OpenCode free**: the bridge permits only `opencode/glm-5.3-flash-free`, `opencode/deepseek-v4.1-flash-free`, `opencode/minimax-m3.1-flash-free` (the code's fixed ZDR allowlist). [Zen/model docs](https://opencode.ai/docs/zen) confirm zero retention and no training for GLM and DeepSeek; **Unverified**: MiniMax's free endpoint is absent from that page's free list. Do not expand the code allowlist from this document. Other free models can train on data or log it; Beam retains 30 days without training. No numeric free allowance is published there; availability is temporary. **Unverified**: IP-based limits/no-login access.
- **Zen / Console pay-as-you-go**: buy credits, pay per request; no subscription allowance. Models include OpenAI, Claude, Gemini and open families. [Model/privacy docs](https://opencode.ai/docs/zen) list retention exceptions; zero retention is not universal. Check the endpoint's privacy row before use.
- **Go ($10/month)** and **Go Plus ($40/month)**: [Go docs](https://opencode.ai/docs/go) list GLM, Kimi, DeepSeek, Qwen, MiniMax, Luna, Haiku, Argon and others. Each model has a monthly dollar allowance: five-hour window 20%, weekly 50%, monthly 100%. Example GLM-5.3: $15/month Go, $120 Go Plus. These are usage allowances, not account balances.

[Go privacy table](https://opencode.ai/docs/go#privacy) applies to both Go tiers: Luna, Haiku 5.5, Grok and Beam retain 30 days without training; Argon, GLM, Kimi and MiniMax have zero retention/no training. Muse Spark Contributor models train on requests and are not ZDR. DeepSeek's zero-retention agreement renews monthly; re-check its expiry before use. Workspace privacy settings can block training endpoints and regions. A subscription does not override endpoint retention.

### Claude / Claude Code
[Pro/Max support](https://support.claude.com/en/articles/11145838) documents shared claude.ai/Code five-hour and weekly limits. Max has a separate Fable weekly limit. Fixed message counts and per-tier model lists are **Unverified** in that source; inspect the picker rather than assuming Opus access.

| Tier | Allowance/access |
|---|---|
| Free | Claude Code subscription access Unverified in the cited Pro/Max article |
| Pro | Claude Code included; bound jobs when the allowance is thin |
| Max 5x | Higher capacity option named by support; exact absolute allowance Unverified |
| Max 20x | Higher capacity option named by support; exact absolute allowance Unverified |
| Team | Code included in all seats; Premium seats provide more usage; model list, prices and absolute allowances Unverified here ([organization guide](https://support.claude.com/en/articles/11845131)) |
| Enterprise | Code included in new/self-serve seats; older plans require Chat + Code or Premium seats; prices/model lists/absolute allowances Unverified here ([organization guide](https://support.claude.com/en/articles/11845131)) |
| API | Separate Console credits, API rates and limits; a key can select API billing instead of subscription usage |

Privacy for Pro/Max: training depends on the consumer setting and safety exceptions ([data usage](https://code.claude.com/docs/en/data-usage)); Code retains data 30 days without model-improvement consent, five years with consent. Deleted chats are removed from backend storage within 30 days ([consumer retention](https://privacy.claude.com/en/articles/10023548-how-long-do-you-store-my-data)). Team, Enterprise and API have standard 30-day retention; qualified Enterprise organizations can enable ZDR, which is not a standard entitlement ([commercial data usage](https://code.claude.com/docs/en/data-usage)). **Unverified** here: exceptions for every model/contract; check applicable terms before assuming ZDR.

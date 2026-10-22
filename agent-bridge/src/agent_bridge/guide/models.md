## Plans and model strength (dated reference, last refreshed Oct 2026)
This is the part of the guide that goes stale: the user's plans and a benchmark snapshot. Backend notes (`start --help`) and the live model lists the runner reads stay true longer. A user or project instruction outranks everything here. When a model or plan below is missing or looks changed, say so to the user instead of guessing.

### Plans: how freely to spend each
Checked 2026-10-22 against the live model lists and quotas, the OpenAI Codex, OpenCode and Antigravity pricing pages, and Claude's support article. "Unverified" marks what no source confirmed. Re-check the live ones: `agent-bridge models|quota --backend agy`, `codex-auth list`, `opencode models`.
- **OpenCode free**: zero-retention (ZDR) models only. OpenCode documents these three as zero-retention and never trained on: `opencode/glm-5.3-flash-free`, `opencode/deepseek-v4.1-flash-free`, `opencode/minimax-m3.1-flash-free`. The bridge refuses every other free model (Big Pickle and MiMo may use collected data to improve models; Nemotron logs prompts; Beam does not train on prompts but retains them for 30 days; `agent-bridge models --backend opencode` marks them `free-logged`) and refuses a start with no `--model`, because OpenCode's own fallback may pick one. The docs state no quota and say most free models are offered for a limited time, so the lineup rotates: expect an occasional free-limit (429) error and retry or switch. Unverified: that it is IP-based with no login.
- **OpenCode Go** (not subscribed; for if that changes): $10/month, or Go Plus $40, per OpenCode's Go page. Limits are monthly dollar caps per model, with a 5-hour allowance of 20% of the month, a weekly one of 50%. Includes GLM-5.3, Kimi K3, DeepSeek V4 Pro, Qwen3.8 Max and others, most documented zero-retention; DeepSeek's ZDR agreement is renewed monthly and is currently valid through October 31, 2026. Avoid the `*-contributor` models (Gemini 4 Argon, Muse), which are trained on, and note Luna, Haiku 5.5, Grok and Beam keep prompts 30 days.
- **Gemini Pro (agy)**: the live list has Gemini 4 Argon (low|medium|high, "heavy" tier, its own weekly bucket), Gemini 3.8 Flash (low|medium|high, "cheap" tier, the shared Gemini bucket) and Claude Opus 5.5 (heavy) and Sonnet 5.5 (mid) sharing one weekly "Claude and GPT models" bucket. Argon is the everyday strong model but is capped weekly, so look at the quota; Flash is the cheap bulk option; reserve Opus for high-value work. Antigravity's Google AI Pro row includes everything in Individual, more rate limits and a flexible AI credit pool, but names no models or per-model limits.
- **Codex Plus**: OpenAI's estimates per five hours are Luna 350-3000 messages, Sol 6.1 15-160 (Sol 6 15-150), Astra 5-45. Use Luna and Sol freely; never Astra on Plus.
- **Codex Pro Lite** (the $100 Pro tier; OpenAI's page calls the $100, $200 and $500 tiers all "Pro" and publishes no multipliers): everything in Plus, and "Pro plans currently have no five-hour limit", though weekly limits may apply. Use Luna extremely heavily and Sol heavily; Astra only for high-value work (hard audits, design questions, brainstorming).
- **Codex Free**: Luna only, at Standard speed in the desktop app, subject to rollout.
- **Claude Pro**: Haiku and Sonnet are fine to use; keep Opus for extra-high-value work. Unverified: the support article names no per-plan model list (it says Pro and Max share five-hour and weekly limits with claude.ai, and older pages said Pro had no Opus in Claude Code), so check the model picker before assuming Opus.

### Effort and model strength
Artificial Analysis Intelligence Index and average API cost per task (general reasoning, not coding-specific; dollars are API prices, not plan quota, so read them as relative cost). Rows per effort are at artificialanalysis.ai/leaderboards/models, and the Coding Agent Index (harness plus model) at `/agents/coding-agents`. Each cell is index / $ per task.

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

Others: Argon (Gemini 4, high) 53 / $1.99; Gemini 3.8 Flash high 41 / $1.24; DeepSeek V4.1 Flash max 45 / $0.26; GLM 5.3 max 45 / $2.01. Opus, Sonnet and Fable rows are "with fallback".
- **Small models need effort**: Luna gains 16 points from low to max for $0.0655 more.
- **Large models flatten**: Sol max adds 2 points over high for 2.3x the cost; Astra max adds 2 over high for 1.9x. `high` is the usual ceiling for a large model; `xhigh`/`max` pay only for audits and hard diagnosis. Opus and Sonnet are the exceptions, still gaining at xhigh and max.
- **Size beats effort**: Sol medium (48, $0.21) outscores Luna max (38, $0.07) and beats Sonnet high (47, $0.88). For the same ~50, Sol high costs $0.32, Opus medium $1.34, Astra medium $1.54.

### How to use each model on each plan (a starting point; override for the task)
The same model plays a different role on a different plan, because the plan sets how much it can be used. Effort is limited to what each backend accepts (`agent-bridge start --help`); the top of a range is for audits, deep diagnosis or the user asking, since going past it buys little (see the flattening above). Small-model output always gets a spot-check.

| Model | Plan | Role | Effort | Pattern |
|---|---|---|---|---|
| Luna | Free | the only model: edits, sweeps, first-pass audits | high to xhigh | split work into small bounded jobs and verify more |
| Luna | Plus | bulk workhorse: implementation, sweeps, tests, first-pass audits | high to xhigh | deepest quota (350-3000 messages per 5 hours): the default for anything bounded |
| Luna | Pro Lite | the same, used extremely heavily | xhigh to max | no five-hour limit: repeat sweeps and audits freely; max for audits, still $0.07 a task |
| Sol | Plus | step up when Luna struggles: tricky implementation, diagnosis, review of Luna's diff | medium to high | 15-160 messages per 5 hours: a few jobs per window, one at a time |
| Sol | Pro Lite | real implementation, second-opinion review, diagnosis | high to xhigh | heavy use; the usual reviewer of Luna's work; max is not offered |
| Astra | Plus | never | none | 5-45 messages per 5 hours is too thin to spend |
| Astra | Pro Lite | hardest audits, design and architecture questions, read-only brainstorming | medium to high | one job at a time and never routine; xhigh or max only if the user asks |
| Argon (agy) | Gemini Pro | everyday strong model; a second opinion from another model family | medium to high | its own weekly bucket: read `quota` before a big fan-out |
| Gemini 3.8 Flash (agy) | Gemini Pro | cheap bulk: summaries, log triage, docs, mechanical sweeps | high | shared Gemini bucket, barely used: reach for it before Argon |
| Opus 5.5 (agy) | Gemini Pro | taste-heavy UI/visual work when Claude quota is low; hardest design review | medium to high | shared Claude-and-GPT bucket: reserve; low is weak (42) |
| Sonnet 5.5 (agy) | Gemini Pro | mid-weight UI/visual work | medium to high | the same shared bucket as Opus |
| Haiku 5.5 | Claude Pro | cheap exploration, summaries, quick lookups | high | 38 at $0.08: cheap enough to avoid low |
| Sonnet 5.5 | Claude Pro | UI/TUI/visual taste, work that needs live collaboration | medium to high | the Claude CLI accepts low to high only; spends Claude quota |
| Opus 5.5 | Claude Pro | extra-high-value work only: root-level design decisions | medium to high | reserve it |
| OpenCode free (zero-retention) | free | read-only exploration, summaries, mechanical edits | none | variants are not listed (an unknown one fails the turn); treat as small-model output |

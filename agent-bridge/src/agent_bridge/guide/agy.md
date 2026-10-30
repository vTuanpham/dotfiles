# agy backend (Antigravity CLI)

- Which models agy offers depends on the account: read `model-guide models --backend agy` for what can be started. Gemini Flash is the cheap default. The Claude models (Opus, Sonnet) suit taste-heavy UI/visual work, especially when Claude's own quota is tight; they share one quota bucket, so check `quota` before a large fan-out.
- The model list includes Gemini and Claude IDs with cost tiers and quota buckets; GPT-OSS models are excluded.
- Prefer cheap-tier models unless the task needs more. Quota is tracked per bucket and account; stale cache data is refreshed by the runner.
- Accounts are isolated under `~/.agy-accounts/<a>/`; the user signs in new accounts from a terminal.
- Both modes read anywhere. workspace-write may write the cwd plus writable roots and run commands confined by agy's sandbox, with no network. read-only denies writes and commands.
  - Network or more commands are opt-in through agy's allow rules; deny beats allow.
  - A denial is logged as urgent, and the worker is told once to continue without it.
- Steers queue as the next turn because agy has no mid-turn injection. Interrupt ends the turn and keeps the process. Conversation state is isolated per job and removed with the job.
- Quota out: the runner automatically resumes on another signed-in account with quota left; set `AGENT_BRIDGE_AGY_FALLBACK=0` to disable it. The conversation carries over.
- Waiting costs quota: agy backgrounds any command still running after 10 seconds and has no blocking wait for it, so a worker that waits polls, one full-context request per poll. Its stream-json then goes silent (steps after a still-running one are held back) while quota drains. The runner reads agy's own transcript each minute, logs `model_requests` (count and tokens) and raises one urgent `quota_burn` after three minutes of requests the stream never showed. Interrupt and resume the worker, or run the long command yourself. Briefs should keep agy workers off long benchmarks; the runner also tells them to hand such a command to the coordinator and end the turn. Inherited context is re-billed uncached after an account switch, so a long thread can spend a large share of a weekly bucket in one fallback.

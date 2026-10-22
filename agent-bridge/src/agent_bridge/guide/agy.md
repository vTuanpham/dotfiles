# agy backend (Antigravity CLI)

- Gemini Argon is the everyday model. agy's Claude Opus models are frontier-level (Astra/Argon class) but spend quota fast, so reserve them for high-value work such as taste-heavy UI/visual work when Claude's own quota is tight.
- The model list includes Gemini and Claude IDs with cost tiers and quota buckets; GPT-OSS models are excluded.
- Prefer cheap-tier models unless the task needs more. Quota is tracked per bucket and account; stale cache data is refreshed by the runner.
- Accounts are isolated under `~/.agy-accounts/<a>/`; the user signs in new accounts from a terminal.
- Both modes read anywhere. workspace-write may write the cwd plus writable roots and run commands confined by agy's sandbox, with no network. read-only denies writes and commands.
  - Network or more commands are opt-in through agy's allow rules; deny beats allow.
  - A denial is logged as urgent, and the worker is told once to continue without it.
- Steers queue as the next turn because agy has no mid-turn injection. Interrupt ends the turn and keeps the process. Conversation state is isolated per job and removed with the job.
- Quota out: the runner automatically resumes on another signed-in account with quota left; set `AGENT_BRIDGE_AGY_FALLBACK=0` to disable it. The conversation carries over.

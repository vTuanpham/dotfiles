# codex backend

## Models
Use the newest model of each family (highest version wins; never older or spark); pass exact IDs because a bare family name can select the wrong metadata.
- **Luna**: cheap bulk worker for coding, implementation, bounded sweeps and bug-finding audits (`xhigh|max` for audits). Effort `high|xhigh|max` only. Cheap per token but thinks long, so wall time can exceed Sol's.
- **Sol**: clearly stronger than Luna: tricky implementation, deep diagnosis, review. Effort `medium|high|xhigh`.
- **Astra**: quota-heavy; reserve it for the hardest audits and tasks and for brainstorming (read-only). Effort `low|medium|high` (xhigh/max only when the user asks).

How freely to spend each depends on the plan (the `*` row in `codex-auth list`): see "Plans" at the end of `agent-bridge --help`.

## Specifics
- Steers land inside the active turn.
- workspace-write permits network access; read-only disables it.
- Questions (`question` events) are answered by writing `<job>/inbox/<requestId>.md` within 120 s. Otherwise the worker proceeds on its own judgment.
- Each job runs with a private `CODEX_HOME` (`<job>/home/codex`): its threads, sqlite and logs never reach the user's `codex resume` and are deleted with the job. Instructions, skills, rules and hooks are shared by symlink, `config.toml` is a copy, and the login is a symlink to the real `auth.json`.

## Quota and accounts
When a turn fails with a usage or limit error:
1. Run `codex-auth list`. The 5H/WEEKLY columns are percent remaining from local cache only, so an account idle for hours can show stale numbers. Pro Lite has no 5h limit, so its 5H column repeats the weekly one. Mask emails in any output you show.
2. Switch by email without printing it: `codex-auth switch "$(codex-auth list | awk '$1=="NN"{print $2}')"` (a bare number doesn't match). Burn the Plus accounts first (any with 5h and weekly left), then Pro Lite, then Free.
3. Run `codex app-server daemon restart` so the new login applies; codex-auth alone doesn't.
4. Resume one failed job and confirm it progresses for ~30 s before resuming the rest. If it still fails at once, move to the next account.

Use another backend only when every account is exhausted.

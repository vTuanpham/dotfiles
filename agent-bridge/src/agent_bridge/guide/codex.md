# codex backend

## Models
Use `model-guide models --backend codex --json` for current IDs, native effort
ranges and generated benchmark coverage. Pass exact IDs; family names can resolve
different metadata. The model-selection skill owns task fit and effort advice,
including small-worker reasoning and domain-specific cost/time tradeoffs. CLI
inventory can be wider than a native subagent tool's selectable models.

Read `model-guide read subscriptions` only when the choice depends on a plan or allowance. Check the live account with `codex-auth list`; use `model-guide read models` for generic model/effort advice.

## Specifics
- Steers land inside the active turn.
- workspace-write permits network access; read-only disables it.
- Questions (`question` events) are answered by writing `<job>/inbox/<requestId>.md` within 120 s. Otherwise the worker proceeds on its own judgment.
- Each job runs with a private `CODEX_HOME` (`<job>/home/codex`): its threads, sqlite and logs never reach the user's `codex resume` and are deleted with the job. Instructions, skills, rules and hooks are shared by symlink, `config.toml` is a copy, and the login is a symlink to the real `auth.json`.

## Quota and accounts
When a turn fails with a usage or limit error:
1. Run `codex-auth list`. The 5H/WEEKLY columns are percent remaining from local cache only, so an account idle for hours can show stale numbers. On tiers without a five-hour limit, the 5H column can repeat the weekly value. Live output may label the $100 tier differently from the pricing page. Mask emails in any output you show.
2. Switch to an authorized account with sufficient allowance by email without printing it: `codex-auth switch "$(codex-auth list | awk '$1=="NN"{print $2}')"` (a bare number doesn't match). Choose from live access and remaining windows rather than assuming a particular set of tiers.
3. Run `codex app-server daemon restart` so the new login applies; codex-auth alone doesn't.
4. Resume one failed job and confirm it progresses for ~30 s before resuming the rest. If it still fails at once, move to the next account.

Use another backend only when every account is exhausted.

# agent-accounts

[← Packages](../README.md#packages) · **uv tool** · account observations

```text
Existing provider caches ── agent-accounts ─┬─ Wake quota rows
                                          └─ Bridge status

Selected native session ───────────────────── Inbox session quota
```

Read account inventory without scanning jobs, messages or peer history.
The JSON contract carries account aliases, provider, windows, observation time
and freshness. Codex's local cache has unknown freshness; agy's cache becomes
stale after ten minutes. Addresses are omitted from this shared inventory.

```sh
uv tool install --editable ./agent-accounts
agent-accounts snapshot
agent-accounts refresh --account a1   # explicit agy allowance refresh
```

Snapshot reads existing caches through codex-auth and `~/.agy-accounts/*/quota.json`.
Refresh uses the selected account's existing file login and validates the result
before atomically replacing its private quota cache. It never signs in, switches
accounts or creates an auth store. Refresh without --account queries all existing
signed-in agy accounts. Errors do not include provider stderr or credential data.

Inbox continues to read allowance from the selected native daemon; a machine-wide
cache must not substitute for a conversation's account. This matches
[T3 Code's instance/account isolation](https://github.com/pingdotgg/t3code/blob/main/docs/internals/providers.md).

Checks: `uv run pytest` and `uv run ruff check src tests`.

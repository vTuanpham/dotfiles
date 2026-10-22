# git

[← Packages](../README.md#packages) · **Snapshot** · `./install.sh --apply snapshots` copies a file only when it is missing and never overwrites yours

- `.gitconfig`: identity (the GitHub no-reply address), `safe.directory = *`, and `credential.helper = store`.
  The `store` helper keeps HTTPS credentials in plaintext in `~/.git-credentials`, which is never tracked;
  prefer SSH remotes, or swap the helper for a keyring one.
- `.config/git/ignore`: the global ignore, currently `**/.claude/settings.local.json`.

Change the name and email before using it as your own.

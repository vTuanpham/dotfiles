# Dotfiles: rules for agents working in this repository

This repository is public. Only public-facing material belongs in it; anything personal or tied to one machine
stays out.

## What never goes in

- Credentials of any kind: tokens, keys, cookies, passwords, `.env` files, auth stores.
- The owner's real email (use the GitHub no-reply address), real name, hostnames, and the names of private
  projects or repositories.
- Machine-local state: trusted projects or workspaces, hook trust hashes, approval allowlists, auto-mode
  environment blocks that describe a project, session or history files.

Instead, edit the live file and leave this repository's snapshot generic. If a snapshot has to follow a live
file, copy it, delete the machine-local parts, and run the check below. Approving a project, a hook or a
permission in a tool changes the live file only; nothing flows into this repository on its own.

## How files flow, and what to do

Nothing syncs on its own, in either direction. First find which kind of file you are touching: a folder's
README says "live" or "snapshot", and `install.sh` lists the live links (`LINKS`) and snapshot packages
(`SNAPSHOTS`).

| Kind | Flow | What you do |
| --- | --- | --- |
| Linked (shell rc, `CLAUDE.md`, `AGENTS.md`, skills, `mods`, units, `environment.d`) | The repo file is the live file; `$HOME` links to it | Edit it like any file, remembering it is public. If a tool or installer appended something personal or machine-specific, remove it, or move it to a local file the shell already sources (`~/.config/shell/secrets.local.sh`). Do not commit it. |
| Snapshot (Claude/Codex settings, git, nvim, ranger, rtk, opencode, desktop) | Repo → `$HOME` only, and only when the file is missing | Never copy a live file in wholesale. To follow a live change, copy only the generic part by hand, then run the check. `./install.sh snapshots` lists what differs. |
| Hooks and plugin entries | Repo → live, merged additively | `./install.sh --apply hooks`; it keeps the live file's other content and leaves a backup |
| Reference refresh (`guide/models.md`, `models.lock`) | Generated into the working tree, uncommitted | Follow "Keeping the reference current" in `agent-bridge --help`: re-check the sources, then `refresh --apply --yes` |
| Approvals, trust, auto-mode, generated catalogs | Live only | Leave them where they are; they never belong in this repository |

Adding a new tool's config: decide live link or snapshot, add it to `LINKS` or `SNAPSHOTS` in `install.sh`,
give its folder a README that says which, and add a row to the top-level Packages table. Stage explicit paths,
never `git add -A`. Push only when the user says so.

## Before every commit

```sh
python3 tests/check_public.py     # every tracked file; the pre-commit hook runs the staged form
```

Tools and installers sometimes write into files that are linked here (shell startup files, instruction files,
skills): an installer appends a PATH line, an agent adds a note. Those edits sit in the working tree, visible in
`git status`, and nothing commits or pushes them by itself. Look at them with `git diff` and run
`python3 tests/check_public.py --changed` (also part of `./install.sh check`) before staging, instead of
`git add -A`.

The hook is enabled with `./install.sh --apply githooks` (it sets `core.hooksPath`). Never bypass it with
`--no-verify`. The check reads the names that must never appear from `~/.config/dotfiles/private-terms.txt`,
which lives outside the repository; add a name there as soon as a new private project or account appears.
It reports where and why, never the matching text.

## The rest

- Layout is Stow-style packages (paths mirror `$HOME`; `install.sh` links them), one folder each with its own README (live link or snapshot, stated there). Keep
  that README true when a folder changes, and the top-level Packages table in step.
- `./install.sh` is a dry run unless given `--apply`, and never overwrites a file that differs from the repo.
- Tests: `python3 -B tests/test_shell_startup.py`, `tests/test_install.py`, `tests/test_public.py`, and
  `uv run pytest` inside `agent-bridge/` and `agent-baton/`.
- This history is one clean line from the initial public snapshot. Never merge or push another history into it.

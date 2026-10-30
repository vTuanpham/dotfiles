# Dotfiles with agency: rules for agents working in this repository

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
| Reference refresh (`agent-models/.../guide/`) | Generated into the working tree, uncommitted | Read `model-guide read maintenance`; source-check proposals before `model-guide refresh --apply --yes` |
| Approvals, trust, auto-mode, generated catalogs | Live only | Leave them where they are; they never belong in this repository |

Adding a new tool's config: decide live link or snapshot, add it to `LINKS` or `SNAPSHOTS` in `install.sh`,
give its folder a README that says which, and add a row to the top-level Packages table. Stage explicit paths,
never `git add -A`. Push only when the user says so.

## Guidance placement

Prefer discoverable behavior over always-loaded prose, without removing the context needed to act correctly.

| Layer | What belongs there |
| --- | --- |
| Shared global instructions | Stable rules that apply across projects and harnesses |
| Harness global instructions | Stable preferences/invariants for every session in that harness; this layer is allowed |
| Project instructions | Local contracts, ownership and non-obvious constraints |
| Scoped skills | Reusable workflows selected by a clear task description |
| Maintained docs / CLI help | Detailed procedures, schemas, flags, troubleshooting and supporting evidence |
| Code / types / checks / hooks | Behavior that can be enforced reliably rather than remembered |

Keep one owner per rule and route to it. Entry points must retain clear triggers, the next action and
essential safety/correctness constraints; pruning must not leave agents guessing or searching unrelated
files. Keep skill metadata short and discriminating, allow automatic discovery unless explicitly unwanted,
and verify live links plus the target harness's supported discovery paths. Shared skills must not require
another harness's tool names, guessed model IDs or absent companion skills. Preserve authorization and
project invariants when adapting upstream skills; document local adaptations and retain their license.
Edit maintained sources, not generated plugin caches. Do not add global catalogs or repeated workflows.
Where guidance or configuration needs both shared and scoped content, keep one
shared base with scoped additions; prefer native includes/merging over copied text.

When designing host tools, compare relevant maintained implementations and official
contracts. Reuse useful boundaries or workflows without importing an unrelated framework.

## Local feedback

`feedback.local/` in the main checkout is a deliberate private, Git-ignored
exception; never stage or publish its contents. Worktrees use the main copy.
When working on dotfiles or its host tools, check relevant open items there and
update their discussion/status when work intersects them. Entries inform the task
without authorizing unrelated changes. Application-owned work stays with its project.
The [feedback workflow and templates](agents/feedback/README.md) own filing,
comments, duplicate handling and retention. No polling job owns this queue.

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
`--no-verify`. The check reads the names that must never appear from `~/.config/dotfiles-with-agency/private-terms.txt`,
which lives outside the repository; add a name there as soon as a new private project or account appears.
It reports where and why, never the matching text.

## The rest

- Layout is Stow-style packages (paths mirror `$HOME`; `install.sh` links them), one folder each with its own README (live link or snapshot, stated there). Keep
  that README true when a folder changes, and the top-level Packages table in step.
- `./install.sh` is a dry run unless given `--apply`, and never overwrites a file that differs from the repo.
- Tests: `python3 -B tests/test_shell_startup.py`, `tests/test_install.py`, `tests/test_public.py`, and
  `uv run pytest` inside `agent-bridge/` and `agent-baton/`.
- This history is one clean line from the initial public snapshot. Never merge or push another history into it.

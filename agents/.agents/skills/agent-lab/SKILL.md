---
name: agent-lab
description: Create, resume or retire persistent experiment workspaces outside repositories. Use for scratch work that must survive restarts, provenance tracking and experiment cleanup, with any harness or language; project code changes stay in their repository or Git worktree.
---

# Agent lab

Use `agent-lab --help` for persistent experiments. `new NAME --purpose REASON`
returns a unique ID and infers available session/model/effort context. Let the
tool detect it; supply overrides only when needed and known. Do not guess missing
provenance. Use explicit workspace IDs across sessions.

`path ID` returns `work/` for native edit/file tools. `run ID -- COMMAND ...`
executes there with a cleanup lease; `artifacts/` holds outputs and `tmp/` scratch.
The child receives their paths in `AGENT_LAB_*` and its own `TMPDIR`. Prefer the
created layout over new scratch folders in project roots or the home directory.

`show ID` gives provenance and size warnings; `list --sizes` finds larger labs.
Keep durable findings in the owning project's maintained docs, not a lab-only
note. Use `keep ID` if independent processes/manual work still need the files;
native edits do not acquire command leases.

When exploration is finished, `retire ID --summary OUTCOME` starts a 14-day grace
period; `restore ID` cancels it. GC previews by default and refuses live command
leases, mounts and Git checkouts/worktrees. Applied GC permanently removes only
eligible retired labs; the user timer uses the same rules. See
`~/dotfiles-with-agency/agent-lab/README.md` for storage, provenance and recovery boundaries.

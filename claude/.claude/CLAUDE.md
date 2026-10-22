@~/.config/agents/AGENTS.md

## Status reports
- Routine status (worker/watch events, progress) is one line, no bullet lists. Save detail for findings, decisions, and final results.

## Large files and command output
- Avoid dumping large files or unfiltered command output into context. Search first; read only relevant sections with bounded reads, or filter output with `rg`/`grep`, `head`, or `tail`.

## Delegation
- Root=Opus. Pick each worker's backend per task (Codex, agy, OpenCode via the `agent-bridge` skill) from the model it needs and the quota left; no backend is the default. Also tidy bridge jobs when the Wake mod's tidy scan reports reclaimable space.
- Claude workers are native subagents (Agent tool) only: Sonnet 5.5 (`model: "sonnet"`, effort low|medium|high), for taste-heavy work (UI/TUI layout, visual design) or work needing native/live collaboration, or when Codex is out of quota and the user is away; they spend Claude quota.

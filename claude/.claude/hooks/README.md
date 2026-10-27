# Root stop safety net (live)

`bridge-stop.py` is linked to `~/.claude/hooks/bridge-stop.py` by
`install.sh --apply links`. SessionStart and Stop entries are merged from the
settings snapshot by `install.sh --apply hooks`; installation is explicit.

SessionStart exports the native session ID through Claude's `CLAUDE_ENV_FILE`.
Bridge records it with the owner's next root command. Stop reads
`agent-bridge status --json --no-quotas`, selecting those owners. With running
workers or unread completions and no kernel-locked root watch, it asks once to
arm a watch or acknowledge results. Private session-scoped pending-set hashes
prevent loops and survive restarts. The hook never starts workers or sends messages.

Subagent events, worker environments, stop-hook continuation, pending native
AskUserQuestion calls and question-like closing text allow stopping. All errors,
incomplete status, missing inputs and timeouts also allow stopping. Existing
sessions can resume after installation so SessionStart supplies their ID.

Disable for a session: `AGENT_BRIDGE_STOP_GUARD=0 claude`.

Contracts: [Stop](https://code.claude.com/docs/en/hooks#stop) and
[SessionStart environment](https://code.claude.com/docs/en/hooks#persist-environment-variables).
Codex/agy roots explicitly arm `agent-bridge watch OWNER --until-event` or poll
`agent-bridge status --json` about every ten seconds.

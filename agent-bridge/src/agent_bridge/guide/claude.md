# claude backend (Claude Code CLI)

- **Models**: the CLI lists aliases `sonnet`, `opus` and `haiku` (marked as aliases); Claude Code has no documented model-list command. Sonnet effort is `low|medium|high`. It spends the user's Claude quota.
  - Use it for taste-heavy work: UI/TUI layout and visual design (its taste beats every Codex model except Astra).
  - Also use it for work that needs live collaboration, or when Codex is out of quota and the user is away.
- **Sandbox**: workspace-write runs Claude's bwrap sandbox (writes limited to cwd plus writable roots, full network) with the auto-mode classifier on top. read-only denies edits and every command outside Claude's read-only set. Denials are logged as urgent.
- **Steers** land inside the active turn. Interrupt ends the turn and keeps the session.
- Worker sessions stay out of the user's Claude resume picker and continue flow, while the bridge resumes them by session id. Nothing needs archiving. Workers load no user mods.

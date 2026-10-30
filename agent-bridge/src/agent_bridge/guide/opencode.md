# OpenCode backend

- **Models**: the model list marks available IDs, unknown effort (`-`) and free/paid tier; variants are not listed.
- **Effort**: effort selects OpenCode's model variant (`provider/model#<effort>`); an unknown variant fails the turn with "Variant unavailable".
- **Privacy**: the free tier is limited to the zero-retention allowlist described in `model-guide read subscriptions`; read it when the choice depends on plan or retention terms. The bridge refuses any other free model and any start without `--model`. Other providers (OpenCode Go, Cerebras, Groq) follow their own terms.
- **Sandbox**: every turn requires `bwrap`; without it the runner fails closed. The filesystem is read-only except cwd and writable roots in workspace-write mode; OpenCode data is private to the job and goes with the job dir. Both modes read anywhere (OpenCode's outside-cwd check is opened; bwrap confines writes). Read-only also denies `edit`, `bash`, `webfetch` and `websearch`. A denial aborts the turn, is logged as urgent, and the worker is told to continue without it.
- **Steers** queue as the next turn; they are not injected mid-turn. Interrupt signals the active turn's process group; stop ends the runner.
- **Sessions**: each prompt runs in a separate process. Later turns reuse the stored session ID.

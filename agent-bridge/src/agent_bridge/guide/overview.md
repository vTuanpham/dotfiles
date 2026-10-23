# agent-bridge workflow

One CLI with four backends: `codex`, `agy`, `claude` and `opencode`.

## Which backend
- **Never bridge to your own harness.** A Claude root uses its Agent tool for Claude workers, a Codex root its own subagents, an agy root its own. The bridge is only for the other harnesses.
- Before launching, read the notes of the backend you will launch in `agent-bridge start --help`: its models, effort levels, quota and quirks.
- No backend is the default: you choose per task, by the model it needs, the plan's quota and the cost. What each is good at: Codex (Luna, Sol) coding, implementation, sweeps and audits; Sonnet (claude), or agy's Claude Opus when Claude quota is tight, taste-heavy UI/visual work; agy a separate quota pool with Gemini and Claude models; OpenCode free models cheap, bounded or non-sensitive work. The plan-by-plan spending guide and the effort/cost table are the dated "Plans and model strength" section at the end of this help. A user or project instruction that states a preference outranks all of it.
- A delegated worker never starts jobs itself; the runner tells every worker so.

## Keeping the reference current
`start` may warn that the model and plan reference is old, that the live model lists changed, or that a refreshed reference is waiting. A weekly job proposes updates and never applies them. When one is waiting you are the reviewer, and you apply it yourself without asking the user:
1. `agent-bridge stale` prints the report path. Read the diff and the worker's notes.
2. Re-check what changed. Fetch each cited source page and confirm every changed number or claim says what the diff says, and look at any new model ids the worker skipped. A claim its source does not support, or changed advice (how freely to spend a plan, which effort to prefer), means `agent-bridge refresh --discard`.
3. Otherwise `agent-bridge refresh --apply --yes`. It edits `guide/models.md` and the lock and leaves them uncommitted; tell the user in one line what changed.
The free-tier zero-retention list lives in code (`ZDR_FREE` in `opencode.py`); changing it is the user's call.

## Jobs
- Flags are in `agent-bridge <command> --help`.
- Use a short owner tag (project + topic) unique to this session; sessions share job storage. Never use `/tmp` for job data.
- Prepare a clear brief before starting a job. Reviewers need network for docs, API contracts and test scratch: start them workspace-write with `--writable-root <job>/out`, brief "don't edit the repo; scratch only under <job>/out", and check `git status` afterwards.
- Approvals are auto-declined. Never bypass a backend's sandbox.
- Every job runs in a systemd user scope inside `codex.slice`, with per-job memory/CPU caps configured by `CODEX_JOB_MEMORY_MAX` and `CODEX_JOB_CPU_QUOTA`. Check available memory, CPU and the effective slice limits before choosing concurrency; do not assume a particular host size. A runaway worker is OOM-killed in its scope. Brief data-heavy agents to stream or chunk.

## Watch and wait
- Which events are urgent: an agent message starting `URGENT:`, questions, errors, declined approvals or denials, and turn completion. Everything else is info and stays in `live.jsonl` (`grep '"kind":"message"' <job>/live.jsonl`).
- The runner injects the URGENT/info rule into every worker, so briefs needn't repeat it.
- Watch covers the selected owner directories and picks up new jobs while it runs.
- Launch with `start ... --watch` (or `resume ... --watch`) as a background command of your harness. It starts the worker detached, prints the job path, then stays until the first urgent event, so one command covers the job and no event is missed: reading begins at the log size from before the launch. `--watch SECONDS` (default 1800) bounds it; exit 124 means the time passed and the worker still runs. Keep bridge calls plain so harness allow rules match them.
- Handle the event, timeout or interrupted watch, then re-arm while jobs still run: `agent-bridge watch <owner> --until-event --timeout 1800` in a background terminal (it also covers several jobs or owners). A bare watch tails existing logs from their end, so arm it first, then check the jobs' results and `live.jsonl` for unhandled urgent events.
- Native harness triggers may replace the watch where they cover the relevant events: Claude Code can launch `start` without `--detach` as a background command for its exit notification.
- Keep doing your own work while workers run; prefer background waits. If one runs longer than its task warrants or goes quiet, read `tail <job>/live.jsonl` and `<backend>.stderr.log` early, then steer it, stop it, or take over.
- If a blocking wait is necessary, use a timeout of at least 180 seconds, subject to harness limits. Tool yield intervals are separate from command timeouts. Avoid foreground sleeps and short polling; a `pgrep -f` or `pkill -f` pattern can match the waiting shell itself.

## Steer, resume, peers
- **Steer**: queues a message; delivery during a turn depends on the backend. For an idle job, `agent-bridge resume <owner>/<name>` delivers the queued message and starts a turn.
- **Interrupt and stop**: interrupt ends the current turn; stop ends the runner.
- **Resume**: keeps the same session and sandbox. For writes after a read-only audit, start a fresh workspace-write job; never edit `state.json`.
- **Peers**: workers under the same owner message each other. An agent message starting `TO <job>[, <job>]: ` is delivered as a steer into that job. Name peers and their file ownership in each brief, so cross-area requests go worker-to-worker. There is no `TO root`: workers reach root only with `URGENT:`.
- **Takeover**: watch, steer or resume another owner's jobs only when the user asks; find them with `owners` and use the full `<owner>/<name>`.
- **Reporting**: brief agents to message only for blockers, questions, concrete checkpoints (edits done plus check results) and the final report. Relay to the user only those checkpoints and the final results.

## Briefs, trust, review
- **Briefs**: state the objective, owned files, constraints, checks, and "edit only, no git writes / no commit/push".
  - Workers auto-load their harness's global and project instruction files, so never tell them to read those; name only the routed guides they need.
  - Look at existing/legacy code first and reuse only where it fits. Keep hot-path performance.
  - Pre-approve routine bug fixes (reported as info), so URGENT stays for real decisions.
- **Triage**: do small fixes yourself. Group findings by owning area into one worker, order work around redesigns, and never put two writers in the same files. Parallelize only the independent rest. Keep hard design and debugging yourself.
- **Trust** scales with model size: the smaller the model, the more skeptical.
  - Small-model output always gets your own diff spot-check plus a separate review round before merge.
  - Mid-size models get your review, plus a separate round for risky areas. Even the largest still gets verified.
  - A worker's "checks passed" is a claim until you rerun the checks.
- **Review stance**: workers tend to over-engineer, over-write tests and over-report. Treat findings as claims to verify and diffs as drafts: cut them down to the minimal fix plus one focused regression test. Reviewers tend to stop at the first confirmed bug, so brief them to sweep their whole scope and report every finding plus what they covered.
- **Second opinion**: for risky changes or uncertain diagnoses, get an independent read-only review (models per backend guide).

## Worktrees
- Writers each get their own git worktree and branch (`git worktree add ../<repo>-<name> -b <name> main`). Sandboxed workers can't write a worktree's git metadata, so root does all commits and rebases.
- Merge the reviewed branches, then remove the worktrees. Cap concurrent test-running writers to what the host can take; read-only reviewers are light.

## Cleanup (root's job, never the user's)
- Once a job's result is merged or discarded:
  1. Remove its worktree (`git worktree remove`, no `--force`).
  2. Run `agent-bridge retire <owner>/<name>` to archive its prompt and final report, then delete the job dir.
- At the end of a session, tidy finished jobs older than 3 days the same way. List a dirty worktree or anything still running for the user's OK; never delete it.

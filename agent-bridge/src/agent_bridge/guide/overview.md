# agent-bridge workflow

One CLI with four backends: `codex`, `agy`, `claude` and `opencode`.

## Which backend
- **Never bridge to your own harness.** A Claude root uses its Agent tool for Claude workers, a Codex root its own subagents, an agy root its own. The bridge is only for the other harnesses.
- Before launching, read the notes of the backend you will launch in `agent-bridge start --help`: its models, effort levels, quota and quirks.
- No backend is the default: you choose per task, by the model it needs, the plan's quota and the cost. What each is good at: Codex (Luna, Sol) coding, implementation, sweeps and audits; Sonnet (claude), or agy's Claude Opus when Claude quota is tight, taste-heavy UI/visual work; agy a separate quota pool with Gemini and Claude models; OpenCode free models cheap, bounded or non-sensitive work. The plan-by-plan spending guide and the effort/cost table are the dated "Plans and model strength" section in `agent-bridge guide plans`. A user or project instruction that states a preference outranks all of it.
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
- Which events are urgent: an agent message starting `URGENT:`, questions, errors, declined approvals or denials, turn completion, queued steers requiring resume, and a running job going silent past `--stall-min` (default 15 minutes; once per silence). A silent turn with an idle worker process usually means a hung model stream: interrupt it and `resume` the same job. Everything else is info and stays in `live.jsonl` (`grep '"kind":"message"' <job>/live.jsonl`).
- The runner injects the URGENT/info rule into every worker, so briefs needn't repeat it.
- Watch covers the selected owner directories and picks up new jobs while it runs.
- Launch with `start ... --watch`, `resume ... --watch`, or `steer <job> "message" --watch` as a background command of your harness. Start and resume run detached; steer resumes an idle job detached or uses its existing runner. Then the command stays until the first urgent event, so one command covers the job and no event is missed: reading begins before launch or enqueue. `--watch SECONDS` (default 1800) bounds it; exit 124 means the time passed and the worker still runs. Keep bridge calls plain so harness allow rules match them.
- Every watch first replays unacknowledged urgent events, including completions from stopped jobs, then follows live events. `--until-event` exits with a compact job/kind/time summary of every event found and everything still unacknowledged. Printing never acknowledges: handle the events, then `agent-bridge ack <owner>` (or `<owner>/<job>`) acknowledges only events already displayed by watch. Events arriving after that display remain pending. `agent-bridge result <job>` acknowledges that job's completions read before the call, leaving questions, errors and other urgent events pending. Ack is explicit even after a timed-out or interrupted watch.
- Re-arm with `agent-bridge watch <owner> --until-event --timeout 1800` in a background terminal; several jobs or owners can share a watch. Pending events replay even if no jobs are running; after handling them, re-arm only for running work. No separate result/log sweep after arming is needed. Watching alone never starts work.
- Owner tags are root namespaces: use a unique owner for each root. Cursors live in `$AGENT_BRIDGE_HOME/jobs/<owner>/ack.json` (default `~/.local/state/agent-bridge/jobs/<owner>/ack.json`), version 1 with `jobs` keyed by job name. Each cursor stores log identity `log` (`device:inode`) and byte offsets `through` (explicitly acknowledged), `seen` (displayed), and `completed` (completions acknowledged by result). Owner locking and atomic writes protect concurrent watches/results. Missing cursors replay existing urgent history; replaced or shortened logs reset that job's cursor. Old jobs need no migration.
- Native harness triggers may replace the watch where they cover the relevant events: Claude Code can launch `start` without `--detach` as a background command for its exit notification.
- Keep doing your own work while workers run; prefer background waits. If one runs longer than its task warrants or goes quiet, read `tail <job>/live.jsonl` and `<backend>.stderr.log` early, then steer it, stop it, or take over.
- If a blocking wait is necessary, use a timeout of at least 180 seconds, subject to harness limits. Tool yield intervals are separate from command timeouts. Avoid foreground sleeps and short polling; a `pgrep -f` or `pkill -f` pattern can match the waiting shell itself.

## Steer, resume, peers
- **Steer**: `agent-bridge steer <owner>/<name> "message"` delivers to the existing runner, or resumes an idle job detached in the same session and sandbox. Delivery during a turn depends on the backend. The runner also checks for late steers before exiting, so a finishing turn cannot strand a follow-up. Add `--watch` to follow it in the same background command. Use `--queue` to queue without starting an idle job, then `resume` once to deliver the batch in order (`--queue` and `--watch` are mutually exclusive). A live runner may still consume queued messages. Retired jobs require `restore` first; watching alone never starts work.
- **Questions**: steering a live runner awaiting an answer keeps that runner and its pending question. For Codex native questions, answer through `<job>/inbox/<requestId>.md`; a steer is a follow-up, not a native question answer.
- **Interrupt and stop**: interrupt ends the current turn; stop ends the runner.
- **Resume**: keeps the same session and sandbox. For writes after a read-only audit, start a fresh workspace-write job; never edit `state.json`.
- **Compact**: `agent-bridge compact <owner>/<name>` supports idle codex and claude jobs only. Claude reports a no-op when there is too little history; compaction leaves queued steers for a later resume.
- **Peers**: workers under the same owner message each other. An agent message starting `TO <job>[, <job>]: ` queues a steer for that job's runner; peer messages do not start idle jobs. Name peers and their file ownership in each brief, so cross-area requests go worker-to-worker. Plain messages already reach root as info; `TO root`, `TO coordinator` or `TO <owner>` are treated the same way, not as unknown peers. A worker that needs root to act now starts its message with `URGENT:`.
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
- Keep jobs available for related follow-ups, verification and review. Retire only when the work is resolved and you are confident its context is no longer needed; a completed turn, saved report or merged result alone is not enough.
- Run `agent-bridge retire <owner>/<name>` once that condition holds. Retirement archives its prompt head and final report, hides it from active listings/watch/sessions, and records `retiredAt` and `purgeAfter` in its state. The job directory, backend homes, session IDs and worktrees stay in place.
- Retirement is reversible until the data is purged: `agent-bridge restore <owner>/<name>`, then `agent-bridge resume <owner>/<name>` continues the same native thread/session. Passing the purge date alone does not delete data, so restore still works until purge actually runs.
- The default retention is 14 days from retirement. Set it for a job with `retire <owner>/<name> --keep-days N` (positive whole days). Repeating retire does not reset its date; restore and retire again to set a new window.
- `agent-bridge purge` explicitly deletes all retired jobs past their recorded purge date; `purge <owner>/<name>` targets just one eligible job. Nothing purges automatically. Wake's tidy scan counts only expired retired jobs, excluding dirty worktrees and live runners, and asks the root to use `purge`. Purge removes clean `out/wt` git worktrees without force and refuses dirty/unreadable worktrees or live runners.
- For immediate disk recovery, `retire <owner>/<name> --purge` archives and permanently deletes that job, bypassing retention. Restore cannot recover purged data. `result <owner>/<name>` still reads the live report while retained, or the archived final report after purge (including older archives); archives contain only the prompt head and up to 2,000 report characters, not native sessions or full transcripts.
- At the end of a session, review finished work before retiring it; age alone is not a reason to retire. Keep worktrees needed for follow-ups. List dirty worktrees or anything still running for the user's OK; never force-delete them.

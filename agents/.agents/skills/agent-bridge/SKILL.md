---
name: agent-bridge
description: Delegate work to workers of another harness (Codex, Antigravity/agy, Claude Code, OpenCode) through the shared `agent-bridge` CLI, and coordinate them live (launch, watch, steer, resume, clean up). Use when you are the root and the user wants work delegated, fanned out, reviewed by another model, or a second opinion. Never use it as a delegated worker.
---

# agent-bridge

A CLI that lets a root agent drive workers of the other harnesses (Codex, agy, OpenCode, and Claude for testing). You start a job with a written brief, watch it live, steer or interrupt it, and review its result. Jobs persist under `~/.local/state/agent-bridge`, so any root can resume or take over, and workers can message each other.

To take over an existing owner namespace from another known root, run `agent-bridge handoff OWNER` first. Ordinary commands from the prior root are then refused; workers and their history remain in place.

## When to reach for it
- The user asks to delegate, fan work out in parallel, get a second opinion, or have another model review a change.
- You pick the backend per task from the model it needs and the quota left; none is the default unless the user's instructions say so. Codex suits coding and audits, agy is a separate quota pool (Gemini and Claude models), OpenCode's free models suit cheap, non-sensitive work, and Claude suits UI and visual work (a Claude root uses its own agents for that, not the bridge). `agent-bridge guide workflow` says how to choose; `agent-bridge guide plans` covers current model rankings.

## How it goes
1. Write a clear brief (objective, owned files, constraints, checks), then `agent-bridge start` a job under a short owner tag unique to your session. Choose a group policy when launching several workers: `group set OWNER NAME --wake all --members a b --max-wait 30m`, then `start ... --group NAME`. Defaults batch completions for 60 seconds; `--settle 0s` gives immediate wakes. `quiet` defers completion wakes; unread results still wake the root after 15 minutes by default when a watch remains armed.
2. Run `agent-bridge start ... --watch` as a background command and keep working. It starts the
   worker detached, then wakes on an urgent event (`URGENT:` message, question, error or turn
   completion batch). A Codex watch continues after that wake only while a reminder or group
   completion is scheduled; it exits otherwise, even if a worker remains. No event is missed: it
   reads from before the launch. The timeout bounds ordinary waiting; while a reminder is
   actually pending, a Codex watch can remain alive past it, even before its first notification.
   After acknowledgement clears the reminder, the original timeout applies again if workers
   remain. Other harnesses exit
   at the event. If no wake or scheduled reminder is pending, the command exits 124 after
   30 minutes with a worker still running.
   Reuse the running session instead of short polling or repeated restarts. If a blocking wait is
   necessary, use a timeout of at least 180 seconds, subject to harness limits; keep the root responsive.
3. Read the watch's job/kind/time summary and handle every event. Printing never acknowledges:
   `result <job>` acknowledges its completions; `ack <owner>` (or `<owner>/<job>`) acknowledges
   urgent events already displayed by watch. New arrivals stay pending. Re-arm with
   `agent-bridge watch <owner> --until-event --timeout 1800` in a background terminal: every
   watch replays unacknowledged critical events before following live work, even for stopped jobs.
   Completion digests wake once per batch; results stay unread until `result` or `ack`.
   No separate result/log sweep after arming is needed. After handling pending events, keep a
   watch armed while jobs run or a schedule remains. A Codex watch continues itself through
   scheduled reminders (`next_reminder_at`); re-arm after an event if jobs remain but no schedule
   does. Other harnesses must re-arm for reminders. Re-arm a Codex watch that errors or is stopped;
   no observer means no reminder push. For a follow-up, `steer <job> "message"` delivers to
   a running worker or resumes an idle job detached in the same session. Add
   `--watch` to follow it in the same background command. Use `--queue` to batch
   steers before an explicit `resume`. Retired jobs need `restore` first;
   watching alone never starts work.
4. Treat a worker's "checks passed" as a claim: verify the diff and rerun the checks before you merge.
5. Keep the job available for related follow-ups, verification and review after a result arrives. Retire only when its work is resolved; a completed turn or saved report is not enough. `agent-bridge retire <owner>/<name>` archives its report and hides it, keeping its session for 14 days by default (`--keep-days N`). Use `restore <owner>/<name>` before `resume` to continue the same session. `purge` deletes only retired jobs past their purge date; `retire --purge` deletes immediately and cannot be undone. Retiring is your job, not the user's; details in `guide workflow`.

The CLI documents itself. Run `agent-bridge --help` for the command map, `agent-bridge guide workflow` for the full workflow (routing, watching, briefs, review, cleanup), `agent-bridge guide plans` for plans and model strength, and `agent-bridge start --help` for each backend's models and quirks. Read them when you need them, not before.

For root-delivery internals or troubleshooting, read only that root's harness reference:
[Codex](references/codex-watch.md),
[Claude Code](https://code.claude.com/docs/en/tools-reference#background-commands),
[Antigravity](https://antigravity.google/docs/subagents?tab=cli), or
[OpenCode](https://opencode.ai/docs/tools/).

- Never bridge to your own harness: a Claude root uses its Agent tool, a Codex root its own subagents, an agy root its own.
- Never bypass a backend's sandbox, never put job data in `/tmp`, and delegate only when the user asked for it.

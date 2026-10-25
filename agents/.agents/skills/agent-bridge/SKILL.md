---
name: agent-bridge
description: Delegate work to workers of another harness (Codex, Antigravity/agy, Claude Code, OpenCode) through the shared `agent-bridge` CLI, and coordinate them live (launch, watch, steer, resume, clean up). Use when you are the root and the user wants work delegated, fanned out, reviewed by another model, or a second opinion. Never use it as a delegated worker.
---

# agent-bridge

A CLI that lets a root agent drive workers of the other harnesses (Codex, agy, OpenCode, and Claude for testing). You start a job with a written brief, watch it live, steer or interrupt it, and review its result. Jobs persist under `~/.local/state/agent-bridge`, so any root can resume or take over, and workers can message each other.

## When to reach for it
- The user asks to delegate, fan work out in parallel, get a second opinion, or have another model review a change.
- You pick the backend per task from the model it needs and the quota left; none is the default unless the user's instructions say so. Codex suits coding and audits, agy is a separate quota pool (Gemini and Claude models), OpenCode's free models suit cheap, non-sensitive work, and Claude suits UI and visual work (a Claude root uses its own agents for that, not the bridge). `agent-bridge guide workflow` says how to choose; `agent-bridge guide plans` covers current model rankings.

## How it goes
1. Write a clear brief (objective, owned files, constraints, checks), then `agent-bridge start` a job under a short owner tag unique to your session.
2. Run `agent-bridge start ... --watch` as a background command and keep working. It starts the
   worker detached, then exits on an urgent event (`URGENT:` message, question, error or turn
   completion), when no runner remains, or after 30 minutes (exit 124, worker still running).
   No event is missed: it reads from before the launch. Reuse the running session instead of
   short polling or repeated restarts. If a blocking wait is necessary, use a timeout of at
   least 180 seconds, subject to harness limits; keep the root responsive.
3. Handle the event, timeout or interrupted watch, then check job state. Re-arm only if at least one job is running:
   `agent-bridge watch <owner> --until-event --timeout 1800` in a background terminal. A bare
   watch tails existing logs from their end; after confirming running work and arming it,
   check the jobs' results and `live.jsonl` for unhandled urgent events. Do not watch an
   owner with no running jobs. For a follow-up, use `steer` only while the target is
   running; if its turn has finished, use `resume` on the same job to start a turn.
   Steering an idle job only queues text; watching it does not make it run.
4. Treat a worker's "checks passed" as a claim: verify the diff and rerun the checks before you merge.
5. Keep the job available for related follow-ups, verification and review after a result arrives. Retire it only when its work is resolved and you are confident its context is no longer needed; a completed turn or saved report is not enough. Then `agent-bridge retire <owner>/<name>` archives its report and frees the disk. Retiring is your job, not the user's.

The CLI documents itself. Run `agent-bridge --help` for the command map, `agent-bridge guide workflow` for the full workflow (routing, watching, briefs, review, cleanup), `agent-bridge guide plans` for plans and model strength, and `agent-bridge start --help` for each backend's models and quirks. Read them when you need them, not before.

- Never bridge to your own harness: a Claude root uses its Agent tool, a Codex root its own subagents, an agy root its own.
- Never bypass a backend's sandbox, never put job data in `/tmp`, and delegate only when the user asked for it.

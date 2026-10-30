---
name: agent-bridge
description: Run persistent workers in a different harness through Agent Bridge, with live steering, watch and retirement. Root only; same-harness workers use native tools.
---

# Agent Bridge

Persistent jobs, steering and event delivery across Codex, Antigravity, Claude
Code and OpenCode. Before launching, read `agent-bridge guide workflow`, then the
selected backend's `agent-bridge start --help`. The `delegation` skill owns shared
coordination guidance; `model-selection` owns model and allowance references.
These CLI guides own current defaults, group policies and exact flags.

- Give each root a unique owner namespace and each job a clear brief with file
  ownership, constraints and checks. Taking over another root's jobs needs
  authorization and `agent-bridge handoff OWNER` first. Preserve sandbox boundaries;
  job data belongs in persistent Bridge storage, not `/tmp`.
- Launch `start ... --watch` in a background terminal and keep independent work
  moving. A standalone watch is `watch OWNER --until-event --timeout 1800`.
  Reuse the running watcher. Blocking waits should be at least 180 seconds when
  the harness permits; tool yield intervals and task timeouts are separate.
- Printing is not acknowledgement. Read `result JOB` for completions; `ack OWNER`
  acknowledges urgent events already displayed. New arrivals remain pending.
  Keep a watch armed for unresolved jobs or scheduled wakes. Codex can retain
  its watcher through scheduled reminders; after an event without a remaining
  schedule, re-arm if jobs remain. Other harnesses must re-arm for later events.
- `steer JOB "message" --watch` reaches a live worker or resumes its idle session.
  `--queue` queues without starting an idle worker; `resume` starts it. A live
  worker may consume queued messages. Retired jobs need `restore` first.
- Verify worker findings and checks. Keep jobs useful for follow-ups and review;
  retire when their work is resolved and context is no longer needed. Purge is
  permanent; use the guide's retention/cleanup checks, not age alone.

For delivery troubleshooting, read only the relevant reference:
[Codex](references/codex-watch.md),
[Claude](https://code.claude.com/docs/en/tools-reference#background-commands),
[Antigravity](https://antigravity.google/docs/subagents?tab=cli), or
[OpenCode](https://opencode.ai/docs/tools/).

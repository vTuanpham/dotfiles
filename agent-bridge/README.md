# agent-bridge

[← Packages](../README.md#packages) · **uv tool** (editable) · [Install](#install) · [When a worker needs you](#when-a-worker-needs-you) · [Restore](#restore-and-root-access) · [Model references](#model-references)

A cross-harness CLI that lets a root coding agent (Codex, Antigravity/agy, Claude Code or OpenCode) hand work to workers of
the other harnesses: start a job from a written brief, watch it live, steer or interrupt it, and review its result.
Keep the job for related follow-ups; retire it only when its work is resolved and its context is no longer needed.
`retire <owner>/<name>` archives the report and hides the job, keeping its data in place for
14 days by default (`--keep-days N`). `restore <owner>/<name>` makes it active again, and
`resume` continues the original thread/session. `purge` deletes expired retired jobs only
when explicitly run; `retire --purge` deletes immediately. Both keep archived reports readable
with `result`, but purged sessions cannot be restored. See `agent-bridge guide workflow`.
Jobs persist under `~/.local/state/agent-bridge`, so another root can resume or take over, and
workers can message each other with `TO <peer>:`. Plain worker messages, including ones addressed `TO root:`,
go to the coordinator as info.

To take over an existing owner namespace from a different known root, run
`agent-bridge handoff <owner>` once from the new root. The previous root can
still inspect shared status, but its job mutations, acknowledgements and watch
delivery are refused after the handoff. Unknown/rootless callers retain legacy
access without replacing a known binding.

`agent-bridge steer <owner>/<name> "follow-up"` delivers to a running worker, or
resumes an idle job detached in its original session. Add `--watch` to follow the
new work in the same background command. Use `--queue` to batch messages without
starting an idle job, then `resume` to deliver them in order. Retired jobs require
`restore` first. Watching alone never starts work.

`agent-bridge sessions` exports a versioned JSON inventory of native worker IDs
across all owners and backends, excluding retired jobs, for tools such as [Agent Inbox](../agent-inbox/README.md).
It contains job identity and recorded launcher metadata, never prompts, credentials
or account settings. New jobs record a parent when the root exposes its native
session ID. Other harnesses can supply `AGENT_BRIDGE_ROOT_HARNESS` and
`AGENT_BRIDGE_ROOT_SESSION` for that invocation; older jobs keep an unspecified
parent rather than guessing one. Workers cannot export other owners' inventory.

![The root briefs workers across four harnesses, then reads their persistent job state to handle blockers and verify results.](../docs/images/agent-bridge-flow.gif)

In Claude Code, [Wake](../claude/README.md#crew-and-quota-rows) draws these jobs as crew, with
worker/model/effort labels and an account quota row.

Every harness can use the same versioned object:

```sh
agent-bridge status --json                 # jobs, pressure, quota caches and peer graph
agent-bridge status --json <owner>         # owner or owner/job filter
agent-bridge status --json --storage       # also verify expired retirement and sizes
agent-bridge guide status
```

The [status guide](src/agent_bridge/guide/status.md) documents fields, polling,
unknown readings and additive V1 evolution. The checked-in
[JSON Schema](src/agent_bridge/status.schema.json) ships with the package.
Readers ignore unknown fields and reject unsupported `schema_version` values.
`owners` and `watch` share the job-status producer. Wake's account row reads
`agent-accounts` independently; peer
edges include stable IDs, direction, counts and last-activity timestamps.
Poll about every ten seconds, with storage scans on demand. Reading status never
acknowledges events. A streaming diff mode awaits a reliable cross-source cursor
protocol.

## When a worker needs you

Choose a group policy when launching several workers. Default `each` batches
completions for 60 seconds; `all` waits for the group (optionally `--max-wait`),
and `quiet` leaves results visible. `group set OWNER NAME --wake all --members a b`
configures a group; launch with `--group NAME`. Unread results wake the root once
after 15 minutes by default, including under `quiet`, when a watch remains armed
in every harness. Reminders are observation-driven; without an armed watch, there
is no background push.
The [group contract](src/agent_bridge/guide/status.md#completion-groups-v11)
documents controls and fields. `watch --until-event` delivers completion digests
once and immediately wakes for failures, questions, errors and explicit
blocking/URGENT messages, flushing any held results.
In a Codex root, the watch process sends wake events, timeouts and failures through
the shared [Codex Wake client](../codex-wake/README.md) and the current thread's
native MCP tool, including after the model turn ends. Empty
handled owners exit silently. After its first wake, it remains alive through
scheduled unread reminders and group completions, even with no runners; this may
outlast `--timeout`. Re-arm after an event if a job remains but no schedule is
pending. Other roots still need to re-arm their watch for reminders. A short
startup line confirms delivery is ready; the root needs no separate callback.
Routine messages and slow/stall notices remain visible; `--include-info` also
wakes for them. Group policies still apply with that flag; overdue unread
reminders wake without it. Queue waits and retry status never wake the root.
Re-arming cannot discard a completion. Printing is not acknowledgement:
`agent-bridge result <owner>/<job>` acknowledges that job's completions, while
`agent-bridge ack <owner>` (or `<owner>/<job>`) acknowledges urgent events already
displayed by watch. Handle questions and errors before acknowledging them. New
events arriving after display stay pending. Use a unique owner per root; its
versioned `jobs/<owner>/ack.json` stores per-job byte cursors, with locked atomic
updates. Missing cursors replay old urgent history; old jobs need no migration.
See `agent-bridge guide workflow` for the cursor format and watch lifecycle.
Wake shows names first with compact event ages, marks classifier-assessed silence as
`stalled`, and keeps unacknowledged completions visible as `done`. Known turn
times appear only when useful and space allows.

Workers report questions to their root. The root asks through its native harness,
then uses [Baton](../agent-baton/README.md#unanswered-questions) for one reminder
after about three minutes if it remains active. It reads the answer and explicitly
steers or resumes the relevant Bridge job; no automatic question relay is installed.
Independent jobs can keep running while a decision is pending. Permission and
approval requirements still apply. Baton's
[workflow overview](../agent-baton/README.md#workflow-overview) diagrams this path.

## Install

Install and use (a uv tool, editable from this checkout):

```sh
uv tool install --with-editable ~/dotfiles/codex-wake \
  --with-editable ~/dotfiles/agent-models --with-editable ~/dotfiles/agent-resources \
  --with-editable ~/dotfiles/agent-accounts --editable ~/dotfiles/agent-bridge
agent-bridge --help            # compact command map and workflow rules
agent-bridge guide workflow    # Bridge routing, watching, steering and cleanup
model-guide read models       # generic model strength, effort and costs
model-guide read subscriptions # all vendor tiers; read only for plan-dependent choices
agent-bridge start --help      # each backend's models, effort levels, quota and quirks
```

The documentation is the `guide` and per-command `--help` output on purpose, so a model reads it when it decides to rather than
carrying it in every prompt. It is assembled from `src/agent_bridge/guide/*.md`; the skill in
`agents/.agents/skills/agent-bridge/` is only a short briefing.

Notes:
- **Sandboxes are never bypassed.** Workers run in a systemd scope with memory and CPU caps; OpenCode runs
  under `bwrap`, and only the zero-retention free models are allowed.
- **A worker cannot start jobs**: it carries `AGENT_BRIDGE_WORKER`, which the CLI refuses.
- **Reference updates:** `model-guide read maintenance` owns the review workflow.

Develop: `uv run pytest` and `uv run ruff check .` in this directory.

## Resource integration

[Agent resources](../agent-resources/README.md) owns host admission, queue controls
and cancellation. Bridge injects the worker/job/controller identity, shares the
queue through OpenCode's sandbox mount, and reports waits and pressure without
waking the root. Workers use `agent-resources run --mem SIZE -- <command>`.
The queue preserves the already-filtered worker environment and existing caps.

Choose job caps with `start ... --memory 4G --cpu 400%`, or `resume <job>` with
those flags for its next launch. Caps above effective slice/host budgets are
refused. A plain resume sends `Continue.` in the same native session when no
steers are queued. Transient backend failures get four bounded, jittered retries
on the same model; exhaustion suggests resuming that same thread on another model.

## Worker environment

Worker launches remove variables whose names contain `KEY`, `TOKEN`, `SECRET`,
`PASSWORD`, `CREDENTIAL`, `AUTH` or `COOKIE` (case-insensitive). Normal runtime,
locale, proxy and backend config paths remain available; existing backend auth
files are unchanged. Set `AGENT_BRIDGE_PASS_ENV=NAME1,NAME2` in the root environment
to pass specific variables a job needs. `AGENT_BRIDGE_DENY_ENV=NAME1,NAME2` adds
exact names to remove, taking precedence over pass-through. Lists use exact,
case-sensitive names and reject wildcards or malformed entries without echoing
their contents.

The filter applies at Bridge worker/helper launch. Standalone resource commands
preserve their caller's environment; account queries use their own selected login. Set pass-through before launching a worker: a removed variable
cannot be recovered from its parent environment later. Variables such as
`SSH_AUTH_SOCK` also match the default filter and need explicit pass-through
when required. This filters inherited environments; it does not restrict auth
files or prevent a shell startup file from exporting variables again. Start a
fresh worker process to apply the policy to an already-running backend.

## Restore and root access

Install the editable uv tool as above, then run `./install.sh --apply links` from
the repository root to link its shared skill into each harness. The mapping of
skills and instructions is in [agents](../agents/README.md).

Allow the root to execute the bridge CLI outside its sandbox, read the shared
skill and read/write the jobs directory through its harness's permission controls.
Keep the resulting grants in live machine-local files, outside this public
repository. Follow `agent-bridge guide workflow` for the workflow and `agent-bridge start --help` for backend notes.
Workers carry `AGENT_BRIDGE_WORKER`, which the CLI refuses, so root
access does not grant workers permission to start more jobs. Worker sandboxing
remains in place.

## Model references

Shared model selection and reference maintenance belong to [agent-models](../agent-models/README.md).
Use `model-guide read models` and `model-guide read maintenance`; Bridge consumes their reviewed
reference without owning the refresh process. The delegation skill owns common worker coordination.

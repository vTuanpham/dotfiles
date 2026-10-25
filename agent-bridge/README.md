# agent-bridge

[← Packages](../README.md#packages) · **uv tool** (editable) · [Install](#install) · [When a worker needs you](#when-a-worker-needs-you) · [Restore](#restore-and-root-access) · [Reference refresh](#reference-refresh)

A cross-harness CLI that lets a root coding agent (Codex, Antigravity/agy, Claude Code or OpenCode) hand work to workers of
the other harnesses: start a job from a written brief, watch it live, steer or interrupt it, and review its result.
Keep the job for related follow-ups; retire it only when its work is resolved and its context is no longer needed.
Jobs persist under `~/.local/state/agent-bridge`, so another root can resume or take over, and
workers can message each other with `TO <peer>:`. Plain worker messages, including ones addressed `TO root:`,
go to the coordinator as info.

`agent-bridge sessions` exports a versioned JSON inventory of native worker IDs
across all owners and backends, for tools such as [Agent Inbox](../agent-inbox/README.md).
It contains job identity and recorded launcher metadata, never prompts, credentials
or account settings. New jobs record a parent when the root exposes its native
session ID. Other harnesses can supply `AGENT_BRIDGE_ROOT_HARNESS` and
`AGENT_BRIDGE_ROOT_SESSION` for that invocation; older jobs keep an unspecified
parent rather than guessing one. Workers cannot export other owners' inventory.

![The root briefs workers across four harnesses, then reads their persistent job state to handle blockers and verify results.](../docs/images/agent-bridge-flow.gif)

In Claude Code, [Wake](../claude/README.md#crew-and-quota-rows) draws these jobs as crew, with
worker/model/effort labels and an account quota row.

## When a worker needs you

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
uv tool install --editable ~/dotfiles/agent-bridge
agent-bridge --help            # compact command map and workflow rules
agent-bridge guide workflow    # routing, watching, briefs, review, cleanup and reference refresh
agent-bridge guide plans       # plans, model strength and costs
agent-bridge start --help      # each backend's models, effort levels, quota and quirks
```

The documentation is the `guide` and per-command `--help` output on purpose, so a model reads it when it decides to rather than
carrying it in every prompt. It is assembled from `src/agent_bridge/guide/*.md`; the skill in
`agents/.agents/skills/agent-bridge/` is only a short briefing.

Notes:
- **Sandboxes are never bypassed.** Workers run in a systemd scope with memory and CPU caps; OpenCode runs
  under `bwrap`, and only the zero-retention free models are allowed.
- **A worker cannot start jobs**: it carries `AGENT_BRIDGE_WORKER`, which the CLI refuses.
- **Reference updates:** see [Reference refresh](#reference-refresh) below; the CLI help owns the review workflow.

Develop: `uv run pytest` and `uv run ruff check .` in this directory.

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

## Reference refresh

`agent-bridge stale` compares live model lists with `guide/models.lock`; `start`
warns when the reference is old or a proposal is waiting. `guide/models.md` and
`models.lock` are checked by the [reference timer](../systemd/README.md#startup-and-timers).
The check runs daily; a worker can propose an update at most weekly. Applying a proposal leaves it
uncommitted. Follow **Keeping the reference current** in `agent-bridge guide workflow`:
read the report, re-check its cited sources, then apply or discard. Only a refresh
with no change and no drift resets the staleness clock without root review.

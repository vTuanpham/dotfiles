# Shared status contract

Any harness can read `agent-bridge status --json [owner | owner/job ...]`.
`status.Collector` is the sole producer; types live in `status_model.py`, and
the packaged JSON Schema 2020-12 contract is `agent_bridge/status.schema.json`.
`status_render.py` owns human views. Read JSON directly, never parse text views.

V1 evolves additively: existing fields retain their types, units and meanings.
`schema_minor: 1` adds completion wake groups; older V1 readers ignore those fields.
Readers ignore unknown fields at every level and reject unsupported
`schema_version` values. Incompatible changes require another version. Unknown
readings are `null`, not guessed zeroes. `errors` identifies unavailable/rejected
sources without echoing their contents. Other sources remain usable.

Poll about every ten seconds while jobs run, once a minute when idle. Quotas
need only minute polling. `status` makes no provider/model requests: Codex uses
`codex-auth list`'s local cache, agy uses its existing account caches. Explicit
`quota --backend agy` refresh still works; Wake preserves its refresh schedule
but consumes the numbers through status JSON only. Use `--storage` on demand
or hourly: it scans sizes and checks expired retired worktrees with read-only git.
Ordinary polls leave eligibility/bytes unknown until scanned.

Status never starts, steers, acknowledges, pauses or cancels jobs. Like the
existing heavy scan, it cleans unlocked stale requests under the queue lock.
This is a best-effort observation across changing files, not a transaction across
jobs. Complete JSONL records, atomic state replacement, queue locks and log
identities protect individual boundaries. No `--follow` is provided: resumable
diffs across log replacement, acknowledgements and pressure sampling need a
separate protocol. Polling keeps that protocol out of every harness.

| Section | Fields and purpose |
| --- | --- |
| `generated_at` | UTC observation timestamp. Ages are seconds, memory bytes, CPU seconds or explicitly named microseconds. All timestamps include timezones. |
| `jobs` | Stable `id = owner/name`, identity/model/effort/account, live runner, state/reason, event time/age, stall assessment, configured caps, observed memory/CPU and OOMs, retry counts, current stage, completion visibility and retirement dates. Retired jobs remain in JSON; human views omit them. |
| `owners` | Active/running/unanswered counts and last root command; sizes with `--storage`. |
| `wake_events` | Native critical events and unseen completion digests. Successful native completions remain in `events` and unread counters. Reading status never marks a wake displayed. |
| `events` | Pending default/informational events plus the last 100 events per job. Pending events are never truncated. `wakes` and `informational` encode default and opt-in wake policy. |
| `heavy` | Requests with stable ID, owning job or null, executable basename (no arguments), declared need/exclusivity, state, wait/elapsed seconds, kernel-lock liveness, reserved/budget bytes, pause flag/reason and source errors. Wait time excludes pauses. |
| `pressure` | Host availability/load/shared headroom, cgroup memory/CPU/throttling, historical OOM totals, deltas and attribution when known. |
| `quotas` | Available Codex/agy account caches, window labels/remaining percent/reset text, plan/active flag and freshness. No account addresses. Unsupported backends have no rows; absence means unknown, not unlimited. |
| `retention` | Retired/expired counts, optional verified eligible/dirty counts, reclaim bytes and items. Dirty, unreadable, symlinked or live retired worktrees are never claimed reclaimable. No purge occurs. |
| `peers` | Stable job nodes, directed weighted conversations and bounded deliveries, described below. |
| `dependencies` | Provable heavy exclusivity edges: queued exclusive requests wait for holders, or queued requests wait for an exclusive holder. Targets are `heavy:<request-id>`. |

Job states: `running`, `idle`, `retired`, `waiting_for_heavy`, `paused`,
`retrying`, `blocked_on_question`, `waiting_for_root`. Paused jobs are queued
behind a root admission pause; existing holders continue. `stall.state` is
`known`, `inactive`, `unknown`, `ok`, `slow` or `stalled`, with reason, quiet seconds and
effective threshold. Known waits suppress both pace and silence notices. If queue
state cannot be read, assessment is unknown rather than a guessed stall. Busy
CPU/network work keeps the existing three-times silence allowance. Watch still
starts a fresh silence clock on first observation; notices remain informational.

`log_identity`, `acknowledged_through` and `completed_through` support display
cursors without reinterpreting ack files. Explicit `ack`/`result` retain their
semantics. Wake maps these facts into its existing crew/quota layout. Claude's
separate `statusline.py` renders native Claude session/context/cost input; it
never read Bridge state, so that native-only display remains unchanged.

Private locked observations in the Bridge state's `status/oom.json` preserve
OOM history across CLI readers and worker exits. Scope inodes distinguish reused
paths. First observations have null deltas; subsequent samples compare counters.
Unique observed scopes attribute increments to a job; its observed totals remain
until the job is removed. Shared-slice OOMs without a known unique scope stay
unattributed. A root filtering its view still checks other runners before
attribution. Worker observations preserve known totals but cannot make new
attributions without visibility of all jobs. Scope disappearance alone never
proves an OOM. Memory uses unique job scopes where available, otherwise process-tree RSS (shared pages can count
twice). CPU is sampled process-tree time; inaccessible readings stay unknown.

Codex's text cache has no authoritative sample time: freshness is `unknown`,
`observed_at`/`age_seconds` null. Agy timestamps are fresh for ten minutes,
otherwise stale, matching existing Bridge refresh policy. Freshness is separate
from provider allowances.

## Peer graph

Successful delivery appends typed `peer_sent` data beside the existing message
log: `source`, `target` (`owner/name`), `at`, `message_kind: steer`, UTF-8 `size`
and optional `preview`. Legacy records lacking those fields remain ordinary
history; missing sizes/timestamps are never guessed.

`peers.nodes` contains job IDs. Edges contain stable `id = source->target`,
`source`, `target`, `count`, `last_at`, `last_kind`. Counts cover 24 hours,
independently of the message cap. `recent_messages` contains at most 100
deliveries in that window, oldest first. Timestamp ties use source and numeric
log offset. Message IDs identify a log incarnation and byte offset. UIs can draw
directed arrows weighted by count and faded by last activity.

All four backends already log message text, so previews default on, capped at
160 characters. Secret-like labels reuse the worker environment's secret-name
rule; matching environment values, bearer/private-key markers and common token
prefixes omit the whole preview. Whitespace is collapsed. Null previews render
an omitted marker. Scrubbing is conservative, not permission to send secrets:
full existing messages remain in local logs and status event text. Do not publish
snapshots. `peers` keeps its sibling table and groups `a → b: preview` lines,
newest last per direction. Watch prints deliveries as information. Delivery
records and peer-directed envelopes never wake root, including `--include-info`.
Unknown-peer failures and explicit root messages retain their wake behavior.

## Deliberate limits

- `now_doing` uses existing command/turn stages; detailed tool names/arguments
  need consistent backend instrumentation first.
- File overlap warnings need reliable edit attribution; shared worktree diffs
  cannot identify which worker changed a path.
- General dependencies need explicit wait events; only heavy exclusivity is
  currently proved by persisted state.
- Durable timeline replay needs its own retention/cursor protocol; recent
  history and complete wake backlog cover current readers.
- Per-job quota burn cannot be separated reliably from account cache changes
  during concurrent workers and native retries.

Runtime dependencies remain empty. The locked development-only `jsonschema`
dependency validates actual collector/CLI snapshots against the shipped schema.

## Completion groups (V1.1)

`jobs[].group` is a root-owned label. `groups[]` exposes `id`, `owner`, `name`
(null for the ungrouped bucket), `policy`, `members`, `done`, `total`,
`held_completions` (event IDs), `next_reminder_at`, `settle_due_at`, and
`max_wait_due_at`. `unacknowledged_completions` and
`oldest_unacknowledged_completion_age_seconds` are top-level unread counters.

`group_events[]` contains durable completion batches, partial batches, reminders
and observed OOM notices. Wake-eligible notices also appear in `wake_events`.
They retain the Event shape with offset zero (owner-ledger events, not byte
cursors), plus `owner`, `group`, `jobs`, `missing`, `completion_ids`, and `seen`.
No renderer changes are needed to consume the new fields additively.

The default `each` policy opens a fixed 60-second settle window at the first
unread completion; later results inside it share one digest. `--settle 0s`
restores immediate completion wakes. `all` emits once when every current member
turn finishes, counting failures; `--max-wait` emits a partial list and missing
members instead. Root launch/resume and subsequent native turns define new
batches. Predeclare `--members` before launching fast workers to avoid an early
one-member batch. `quiet` never wakes for successful completions. Critical
events always bypass policies and flush held completions into that wake.

Root commands: `group set OWNER NAME --wake all --members a b --max-wait 30m`,
`start ... --group NAME`, `resume JOB --group NAME`, `group assign JOB NAME`,
`group unassign JOB`, `group list OWNER`, `group clear OWNER NAME`.
Clearing resets policy defaults while retaining labels. Policies and membership
live in private, atomically replaced `OWNER/groups.json`; worker state writes
cannot overwrite them. Missing/corrupt policies use `each`. A separate locked
`group-wakes.json` stores notification IDs/cursors, so a crash cannot append a
duplicate batch. Display marks a digest delivered once; explicit result/ack
still controls unread status. A malformed notification ledger fails open to
immediate native completion wakes rather than hiding work.

Reminders default to 15 minutes and never wake, even with `--include-info`.
They are generated when status/watch observes the owner and appear in the next
watch and status text; no observer means no background push. `--remind off`
disables them; `--repeat-reminders` opts into doubling backoff, capped at a year. Acknowledging
results clears their reminders. `owners[].active_watch` uses kernel locks, not
PID guesses; `root_backend` and `root_session_id` identify the owning session.
Claude's optional repository Stop hook uses these fields to catch an unarmed
watch at a turn boundary; Codex/agy roots should arm a watch or poll the JSON.

# Heavy commands and host pressure

Workers automatically receive this rule: use `agent-bridge heavy --mem SIZE -- <command>`
only for model inference/benchmarks, dataset download/extraction, full test
suites, long-lived local servers/headless browsers, or commands expected to use
more than about 1 GiB or several cores for more than a minute.
Do not wrap worker runners, git, edits, reads, lint, type checks or targeted tests.
Everything else runs directly; the bridge does not automatically wrap commands.
Declare the expected peak with `--mem` (for example `1G` or `2500M`). Add
`--exclusive` only for timing measurements, never for test suites. Fitting jobs
run concurrently. Wrap a compound job with `agent-bridge heavy --mem 1G -- sh -c '...'`.
Keep servers in the foreground for their whole lifetime. Do not nest wrappers.
Already-running workers need a steer with this rule; new jobs receive it automatically.
Waiting for a slot is normal, never a blocker or progress message to send. Report
only a holder shown dead while still blocked or a wait exceeding 30 minutes.

```sh
agent-bridge heavy --mem 1G -- uv run pytest
agent-bridge heavy --mem 2500M --exclusive -- ./benchmark
agent-bridge owners
agent-bridge watch <owner>
```

## Admission

The queue is shared across owners, working directories and harnesses of the same
Unix user on one Linux host. It uses `/tmp/agent-bridge-heavy-<uid>` (0700), not
the job directory or a harness's HOME. OpenCode mounts this directory through its
private `/tmp`; sandbox restrictions otherwise remain in force. Other users and
machines have separate queues. `AGENT_BRIDGE_HEAVY_DIR` can relocate it; every
participant must use the same local filesystem directory. Do not delete it while
commands are active or waiting.

A short flock protects admission. Every request holds its own flock, inherited
across exec into the command. Each running request reserves its declared need.
Exit, SIGKILL or an OOM kill releases the lock and reservation; the next scan
discards unlocked request files without PID-based stale-lock guesses.
Command stdio, signals and exit status pass through. An application that explicitly
closes inherited descriptors can drop its lock early; keep such an application
under a foreground shell that waits for it. Backgrounding or daemonizing outside
the wrapper is unsupported. This is cooperative admission, not sandbox enforcement.

Each private `.request` file next to `gate.lock` records job name, executable
basename (no command arguments), start time, PID and PID namespace. Host PID is
recorded directly when known; a host-side `owners`/`watch` scan resolves a
namespaced holder and updates its record. Before that scan, or when host process
visibility is unavailable, it says `host_pid=unavailable` instead of guessing.
The matching `.request.need` file (0600) stores declared need, exclusivity,
queue time and optional job cap. Separate metadata preserves compatibility with
slot-only waiters already running. Requests without this metadata are treated
as exclusive with a 1 GiB need and their recorded cap until they finish.
Wait messages show queue position, every holder's job/command and declared need, elapsed time and
`alive=yes (kernel lock)`, normally every thirty seconds. Kernel lock checks work
across separate PID namespaces. Unlocked holder records are dead/stale and removed;
if admission is still blocked, the waiter reports the dead holder. No holder
record is trusted as proof of liveness without its lock.

Admission requires enough shared memory and headroom. The resource reader checks
`/proc/meminfo` (`MemAvailable`), `/proc/loadavg` (one-minute load), and the
cgroup v2 membership in `/proc/self/cgroup`. It reads `memory.current`,
`memory.max`, `memory.events`, `cpu.max` and `cpu.stat` along the inherited
hierarchy, including the worker's job scope and `codex.slice`. A root outside
that slice also reads the standard user-manager `codex.slice` path when present.
The shared memory budget is the minimum of host `MemAvailable` and
`memory.max - memory.current` for `codex.slice` and its finite ancestors, minus
the safety floor. The caller's smaller job scope does not reduce this shared
budget; that scope still enforces its cap on the command. Without a shared
slice, inherited cgroups and host readings determine the budget. Reclaimable
cgroup cache is deliberately not counted as slack.
Missing controllers are labelled unavailable; malformed or unreadable discovered
budgets stop admission. With no cgroup v2 membership, admission uses host readings.

Admit a request only when the sum of **all running declared needs plus its need**
fits that current budget. Running declarations remain fully reserved even though
some resident memory is already reflected in `MemAvailable`/`memory.current`;
this deliberately conservative accounting leaves room for growth. Status shows
both `heavy_reserved` and `heavy_budget` so the wait is explainable. A need larger
than shared capacity minus the floor is rejected rather than waiting forever.

Omitting `--mem` reserves **1 GiB**. It matches the heavy-work threshold and
avoids charging every unannotated test suite for an entire worker scope. It is a
fallback estimate, not a measured peak: declare larger needs for model/data work.
Memory sizes use positive bytes or K/M/G/T binary units, including exact fractions
such as `1.5G`. This declaration neither allocates memory nor changes cgroup caps.

The oldest fitting request normally goes first. If the head does not fit, the
first smaller request that fits may backfill. After the head has waited **five
minutes**, no more jobs may backfill until it can start. Already-running jobs
continue; the five-minute bound limits new overtaking, not their runtime.
An exclusive request is also a FIFO barrier: jobs behind it cannot backfill past
it. It starts only with no other heavy jobs running and excludes all heavy
admissions until it exits. It does not stop ordinary unwrapped commands.

The first cgroup CPU sample takes one second. Admission then waits while a
limited shared ancestor uses at least 80% of its quota over the sampling interval, or
its throttled-period count increases. Host load remains a separate gate: host
load cannot reliably be attributed to a slice. No cgroups, limits or slice
drop-ins are modified by admission.

| Environment setting | Default | Purpose |
| --- | --- | --- |
| `AGENT_BRIDGE_HEAVY_SLOTS` | Unset: no job-count cap | Optional positive hard cap in addition to memory admission. |
| `AGENT_BRIDGE_HEAVY_MIN_AVAILABLE_MIB` | Existing floor: larger of 1024 MiB and 20% of the smallest host/inherited memory capacity | Reserve memory before admitting more work. `0` disables the reserve. |
| `AGENT_BRIDGE_HEAVY_MAX_LOAD` | 80% of logical CPU count | Leave host scheduling headroom; positive finite values only. |

Set these in the root environment before launching workers so they inherit a
consistent policy. If live requests have different explicit caps, the tightest
cap applies; unset requests do not impose a count limit. Queue position,
memory needs/budget, holders and the wait reason go to stderr on change (at most every five seconds), with
a reminder every thirty seconds. Cancellation while waiting releases the request.

These reserve and CPU thresholds are conservative starting policies, not a
measured guarantee for arbitrary workloads. A single command can still exceed
its budget after admission. Confirm them with representative peak working sets,
queue times, slice OOM counters and repeated benchmark timings on the real host
before relying on declared estimates or increasing concurrency. A process can
grow beyond its declaration; kernel cgroup caps remain the final defense.
Use `--exclusive` for benchmark timing isolation. A memory estimate alone cannot
prevent CPU contention; test suites must not request exclusivity.
Light commands must run directly rather than joining this queue.

## Existing limits and optional caps

Bridge workers already inherit their job scope and slice caps. Their children
stay in those cgroups. Heavy keeps that membership: it never moves a constrained
worker into an unrelated scope to apply another cap. With `--memory-max-mib`, an
inherited cap at least as strict already satisfies the request; a request to
tighten it prints a warning and retains the existing cap. Changing live job or
slice limits is a separate root decision.

For a standalone invocation without inherited memory caps or `codex.slice`, the
flag attempts a systemd user scope with `MemoryMax`. A bounded no-op probe checks
the same properties first. Absent systemd, an inaccessible user bus (including
WSL configurations), or an unsupported scope causes a visible uncapped fallback.
The real command is never retried after a scope launch failure. On systemd
versions with argument expansion, expansion is disabled to preserve literal
arguments. No new cap is enabled by default: a safe working set cannot be guessed
for both model servers and test suites.

`owners` prints host and shared headroom, reserved needs/budget, each running
job's declared need and exclusivity, active/waiting heavy counts, and
inherited limits. `watch` prints them at startup and once a minute, samples every
ten seconds, and warns once per watch invocation about pressure. It also warns
on the slice's initial nonzero `oom_kill` total and each subsequent increase;
historical totals are labelled. CPU usage and throttle counters are shown even
when quota enforcement is absent. These warnings do not acknowledge job events
or change the existing `watch --until-event` completion rules.
Per-job heavy waits appear as queue status and suppress stall notices. They never
wake `--until-event`, including with `--include-info`.

## Failed turns and retries

The runner makes up to four automatic retries for recognizable transient backend
failures, preserving native session and model. Wait ranges are 15–30, 30–60,
60–120 and 60–120 seconds. Each attempt sends only `Continue.` unless a queued
steer takes precedence. Retry waits and intermediate failures are informational;
only exhaustion produces an urgent failure with the retry count and a suggestion
to continue the SAME native session using `agent-bridge resume <job> --model M`.
Non-retryable failures are reported immediately. This continues agent context;
it does not replay a shell command or recap prior work.

Classification is a conservative local policy over native harness errors, informed
by [OpenAI errors](https://developers.openai.com/api/docs/guides/error-codes),
[Claude errors](https://platform.claude.com/docs/en/api/errors), and
[Gemini retry guidance](https://ai.google.dev/gemini-api/docs/troubleshooting).
Those provider APIs distinguish transient overload/rate limits from authentication,
billing and exhausted account quotas; native harness wording may differ. Unknown
errors stay non-retryable. Bridge's four attempts and longer jittered delays are
local limits, separate from retries already performed inside a backend.

## Why this design

[GNU Parallel](https://www.gnu.org/software/parallel/man.html) combines job
counts with `--load` and `--memfree`; its memory policy can kill and requeue the
youngest job below half the threshold. Bridge borrows admission gates, without
killing or replaying potentially stateful worker commands.
[GNU make `-l`](https://www.gnu.org/software/make/manual/html_node/Parallel.html)
also delays new recipes under load, but permits a first job; Bridge waits even
for the first heavy job when the host or slice lacks headroom.

The [kernel cgroup v2 contract](https://docs.kernel.org/admin-guide/cgroup-v2.html)
defines inherited, hierarchical limits, `memory.events` OOM counts and CPU quota
statistics. [systemd resource control](https://www.freedesktop.org/software/systemd/man/latest/systemd.resource-control.html)
recommends `MemoryHigh` for normal control and `MemoryMax` as the last defense;
limits are separate from admission. [systemd-run](https://www.freedesktop.org/software/systemd/man/latest/systemd-run.html)
scope mode preserves the caller's environment and runs synchronously.
[WSL supports systemd](https://learn.microsoft.com/en-us/windows/wsl/systemd),
but that does not establish user-bus availability inside a worker sandbox.

[nice](https://man7.org/linux/man-pages/man1/nice.1.html) and
[ionice](https://man7.org/linux/man-pages/man1/ionice.1.html) change scheduling
priority; they neither reserve memory nor exclude competing benchmarks. Existing
worker niceness stays in place. No additional scheduler or dependency is needed.

---
name: resource-admission
description: Run sustained CPU- or memory-heavy foreground work through the host resource queue. Use for inference, benchmarks, dataset extraction, full suites or long-lived local servers; ordinary lightweight commands run directly.
---

# Resource admission

Read `agent-resources guide` before a heavy run. Declare the expected peak with
`agent-resources run --mem SIZE -- COMMAND ARGS...`; use measured needs when
available. Estimates coordinate admission and do not enforce a memory limit.

Keep the whole command in the foreground. Do not wrap worker runners, nest
admission calls or queue ordinary reads, Git, edits, lint or targeted tests.
Use `--exclusive` for timing isolation only, never for test suites.

Wait in the background through the harness's normal completion mechanism.
Queue waits and root pauses are normal; inspect/report a dead holder or an
unpaused wait over 30 minutes. Root controls live requests with list, cancel,
pause and resume; workers ask their root. Keep inherited caps and sandbox rules.

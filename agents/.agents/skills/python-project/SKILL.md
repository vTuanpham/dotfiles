---
name: python-project
description: Set up or maintain the tooling and quality baseline for substantial Python repository work. Use for Python project development, packaging, CI and quality-tool changes; small scripts need proportional checks.
---

# Python project baseline

Read the project's instructions and existing configuration before changing tools.
Reuse equivalent tooling; do not install a competing formatter, checker, package
manager or runner just to match this list.

- `uv` owns environments, interpreters, dependencies, locks and execution
  (`uv run`). Do not mix ad-hoc pip, virtualenvs or lock owners; document a
  genuinely imposed exception.
- Use `ty` at the latest release, pinned exactly while pre-1.0. Replace an
  existing mypy/pyright setup at the same scope, fixing its findings. Enable
  opt-in rules that catch real bugs, not intentional boundary checks.
- Normal checks: Ruff format/lint, the type checker, pytest with coverage,
  Vulture or an equivalent dead-code limit, pip-audit and fast pre-commit checks.
  Measure before adopting xdist; cap workers to available host resources.
  Put slow coverage, audit, packaging and platform checks in CI.
- Each enabled tool needs checked-in configuration, a canonical command,
  deterministic CI execution, a pinned/locked version and a suppression owner.
  Suppress narrowly, with reasons, and prevent new unexplained suppressions.
- Small scripts can use less, but still verify meaningful behavior and reject
  malformed boundary input. A narrow fix does not authorize unrelated tooling
  migration; establish the baseline when the task includes that scope.

Run the affected checks using the repository's documented commands and inspect
their results. Do not add tests that only restate the implementation.

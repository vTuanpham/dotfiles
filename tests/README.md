# tests

[← Packages](../README.md#packages) · **Repository checks** · nothing is installed

Checks for the repository itself, run from the repository root:

```sh
python3 -B tests/test_shell_startup.py   # Bash and Zsh start quietly, keep cwd and PATH, find their tools
python3 -B tests/test_install.py         # install.sh against a throwaway HOME: dry runs, links, conflicts
python3 -B tests/test_public.py          # the public-facing check: what it refuses, and that this repo passes it
```

`tests/check_public.py` is the check itself, run by the pre-commit hook (`.githooks/pre-commit`, enabled with
`./install.sh --apply githooks`) and by hand as `python3 tests/check_public.py`.

Neither sources credentials or touches your real `$HOME`. The tools have their own suites:
`uv run pytest` in `agent-bridge/` and `agent-baton/`, and Ranger's plugin check under `ranger/`.

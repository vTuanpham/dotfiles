# Codex custom model catalog

`config.toml` points `model_catalog_json` at `gpt-6-models.json`. That file
replaces the catalog the server sends, so it must not be edited by hand or left
to go stale: a hand-kept snapshot is why GPT-6.1 Sol stayed at 272k after the
server default moved to 500k (2026-10-12).

## How it works

`gpt-6-models.json` is **generated**: the live server catalog plus the fields
in `overrides.json`, nothing else.

- `overrides.json`: the only file to edit. Maps a model slug to the fields
  that should differ from the server, e.g. Luna's 1M context window. Add or
  remove entries here; an entry may hold any catalog field.
- `refresh.sh`: fetches the live catalog, merges the overrides, and replaces
  the catalog atomically. On any failure (fetch error, invalid JSON, an
  override naming a slug the server no longer lists) it keeps the old file and
  exits non-zero.
- `.fetch-home/`: a second Codex home without `config.toml`, needed because
  with the pin active `codex debug models` just returns the pinned file. It
  shares the real login through a symlink to `~/.codex/auth.json`; do not put
  a copy of `auth.json` there.

Run `refresh.sh` by hand after changing `overrides.json`, after switching
account plan, or when a model's limits look wrong. Check the result with:

    jq -r '.models[]|[.slug,.context_window,.max_context_window]|@tsv' gpt-6-models.json

Running sessions keep the catalog they started with; restart them (and run
`codex app-server daemon restart`) to pick up a change.

## Schedule

Meant to run hourly from the user's crontab:

    17 * * * * $HOME/.codex/model-catalogs/refresh.sh >/dev/null 2>>$HOME/.codex/model-catalogs/refresh.err

Check `crontab -l` to see whether it is installed. If `refresh.err` grows, an
override probably names a model the server renamed or removed.

## Rules

- Keep per-model context values here. Leave the global/profile
  `model_context_window` unset: it applies to every model and survives model
  switches inside a session.
- The catalog lists what the server offers the active account. Models that
  exist only in the catalog bundled with the CLI (e.g. Daybreak Blue/Red in
  0.162.1) are not included.
- Do not add `model_messages.instructions_template` content through
  `overrides.json` unless the user explicitly authorizes those persistent
  model instructions.

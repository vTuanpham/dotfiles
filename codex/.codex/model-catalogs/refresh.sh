#!/usr/bin/env bash
# Regenerate gpt-6-models.json = live server catalog + overrides.json.
# Keeps the old file and exits non-zero on any failure. See README.md.
set -euo pipefail
export PATH="$HOME/.npm-global/bin:$HOME/.local/bin:/snap/bin:/usr/local/bin:/usr/bin:/bin"

dir="$(cd "$(dirname "$0")" && pwd)"
out="$dir/gpt-6-models.json"
auth="$HOME/.codex/auth.json"
# A second Codex home with no config.toml, so the fetch is not answered by the
# pinned catalog itself. It shares the real login through a symlink.
home="$dir/.fetch-home"
mkdir -p "$home"
ln -sfn "$auth" "$home/auth.json"

tmp="$(mktemp "$dir/.catalog.XXXXXX")"
trap 'rm -f "$tmp" "$tmp.live"' EXIT

CODEX_HOME="$home" timeout 120 codex debug models >"$tmp.live" 2>/dev/null

# If Codex refreshed the token by replacing the symlink, keep the newer login.
if [ ! -L "$home/auth.json" ]; then
  mv -f "$home/auth.json" "$auth"
  ln -sfn "$auth" "$home/auth.json"
fi

jq --slurpfile ov "$dir/overrides.json" '
  $ov[0] as $o
  | if (.models | type) != "array" or (.models | length) == 0
    then error("live catalog has no models") else . end
  | (($o | keys) - [.models[].slug]) as $unknown
  | if ($unknown | length) > 0
    then error("override names unknown model: \($unknown)") else . end
  | .models |= map(. + ($o[.slug] // {}))
' "$tmp.live" >"$tmp"
chmod 644 "$tmp"
mv -f "$tmp" "$out"

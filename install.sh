#!/usr/bin/env bash
# shellcheck disable=SC2317 # the step_* functions are called by name, which shellcheck cannot see
# Restore this machine's tooling from the repo.
#
# A dry run by default: it reports what is missing and what it would do. `./install.sh --apply` does it.
# Safe to re-run, and it never overwrites a file that differs from the repo (it reports the conflict).
#
#   ./install.sh                  report everything
#   ./install.sh --apply          do everything
#   ./install.sh --apply links    do only the named steps
#
# Steps, in order: apt tools uvtools npm links systemd snapshots hooks githooks cron check
set -euo pipefail

REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
APPLY=0
CONFLICTS=0

say() { printf '%s\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }
act() { say "  + $*"; if ((APPLY)); then "$@"; fi; } # prints the command, and runs it only with --apply
# The same text: a CRLF file, or one missing its last newline, is not a difference worth reporting.
same() { [[ $(tr -d '\r' <"$1") == "$(tr -d '\r' <"$2")" ]]; }

# --- apt ---------------------------------------------------------------------------------------------------
step_apt() {
  # package[:command]: a tool counts as present if its command resolves, even when it came from pip or a script
  local want=(stow zsh tmux ranger ffmpeg imagemagick:convert poppler-utils:pdftoppm x11-utils:xwininfo libxtst6 bubblewrap:bwrap jq curl git gh)
  local missing=() entry pkg cmd
  for entry in "${want[@]}"; do
    pkg=${entry%%:*}
    cmd=${entry#*:}
    [[ $entry == *:* ]] || cmd=$pkg
    if [[ $pkg == libxtst6 ]]; then dpkg -s "$pkg" >/dev/null 2>&1 || missing+=("$pkg"); else have "$cmd" || missing+=("$pkg"); fi
  done
  if ((${#missing[@]})); then act sudo apt-get install -y "${missing[@]}"; else say "  all present"; fi
}

# --- standalone tools with an official installer -------------------------------------------------------------
step_tools() {
  have uv || act bash -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
  have starship || act bash -c 'curl -sS https://starship.rs/install.sh | sh -s -- -y'
  have opencode || act bash -c 'curl -fsSL https://opencode.ai/install | bash'
  if ! have tailscale; then
    act bash -c 'curl -fsSL https://tailscale.com/install.sh | sh'
    say "  then sign in: sudo tailscale up"
  fi
  local tool
  for tool in rtk agy; do have "$tool" || say "  MISSING $tool: no scripted install is known, install it by hand"; done
  have nvim || say "  note: nvim is not on PATH (the nvim package is a snapshot only)"
}

# --- uv tools from this repo ---------------------------------------------------------------------------------
step_uvtools() {
  if ! have uv; then say "  uv is missing: run the tools step first"; return 0; fi
  local tool
  for tool in agent-bridge agent-baton agent-inbox portlink; do
    if uv tool list 2>/dev/null | grep -q "^$tool "; then say "  $tool installed"; else act uv tool install --editable "$REPO/$tool"; fi
  done
}

# --- npm globals (Node comes from nvm) -------------------------------------------------------------------------
step_npm() {
  if ! have npm; then say "  npm is missing: install Node 24 with nvm (see README), then rerun this step"; return 0; fi
  local installed missing=() pkg
  installed=$(npm ls -g --depth=0 2>/dev/null || true)
  for pkg in @anthropic-ai/claude-code @openai/codex @loongphy/codex-auth; do
    grep -qF "$pkg@" <<<"$installed" || missing+=("$pkg")
  done
  if ((${#missing[@]})); then act npm install -g "${missing[@]}"; else say "  all present"; fi
}

# --- live symlinks -------------------------------------------------------------------------------------------
# <path in the repo> <link under $HOME>. Every other package is a snapshot (see the snapshots step).
LINKS=(
  "github/.local/bin/github-mcp .local/bin/github-mcp"
  "shell/.bash_logout .bash_logout"
  "shell/.bash_profile .bash_profile"
  "shell/.bashrc .bashrc"
  "shell/.profile .profile"
  "shell/.zprofile .zprofile"
  "shell/.zshenv .zshenv"
  "shell/.zshrc .zshrc"
  "shell/.cuda_paths .cuda_paths"
  "shell/.config/shell/aliases.sh .config/shell/aliases.sh"
  "shell/.config/shell/env.sh .config/shell/env.sh"
  "starship/.config/starship.toml .config/starship.toml"
  "agents/.config/agents/AGENTS.md .config/agents/AGENTS.md"
  "agents/.agents/skills/agent-baton .agents/skills/agent-baton"
  "agents/.agents/skills/agent-bridge .agents/skills/agent-bridge"
  "claude/.claude/CLAUDE.md .claude/CLAUDE.md"
  "claude/.claude/mods .claude/mods"
  "claude/.claude/skills/agent-baton .claude/skills/agent-baton"
  "claude/.claude/skills/agent-bridge .claude/skills/agent-bridge"
  "codex/.codex/AGENTS.md .codex/AGENTS.md"
  "chrome/.local/bin/chatgpt-browser .local/bin/chatgpt-browser"
  "chrome/.local/libexec/chatgpt-browser-idle.py .local/libexec/chatgpt-browser-idle.py"
  "opencode/.config/opencode/AGENTS.md .config/opencode/AGENTS.md"
  "gemini/.gemini/AGENTS.md .gemini/AGENTS.md"
  "gemini/.gemini/config/skills/agent-baton .gemini/config/skills/agent-baton"
  "gemini/.gemini/config/skills/agent-bridge .gemini/config/skills/agent-bridge"
  "systemd/.config/systemd/user/agent-bridge-reference.service .config/systemd/user/agent-bridge-reference.service"
  "systemd/.config/systemd/user/agent-bridge-reference.timer .config/systemd/user/agent-bridge-reference.timer"
  "systemd/.config/environment.d/999-local-bin.conf .config/environment.d/999-local-bin.conf"
)

link() { # link <path in the repo> <link under $HOME>
  local src="$REPO/$1" dest="$HOME/$2"
  if [[ -L $dest && $(readlink -f "$dest") == "$(readlink -f "$src")" ]]; then return 0; fi
  if [[ -e $dest || -L $dest ]]; then
    if [[ -f $dest && ! -L $dest ]] && same "$src" "$dest"; then
      act ln -sfn "$src" "$dest" # an identical copy: safe to turn into the link
    else
      say "  CONFLICT $dest is not the repo's file; resolve it by hand"
      CONFLICTS=1
    fi
    return 0
  fi
  act mkdir -p "$(dirname "$dest")"
  act ln -s "$src" "$dest"
}

step_links() {
  local pair source destination
  for pair in "${LINKS[@]}"; do
    read -r source destination <<<"$pair"
    link "$source" "$destination"
  done
}

# --- systemd user units --------------------------------------------------------------------------------------
step_systemd() {
  if ! have systemctl; then say "  no systemctl here"; return 0; fi
  act systemctl --user daemon-reload
  if systemctl --user is-enabled agent-bridge-reference.timer >/dev/null 2>&1; then
    say "  agent-bridge-reference.timer enabled"
  else
    act systemctl --user enable --now agent-bridge-reference.timer
  fi
  say "  the Codex reset tracker unit comes from its own repo: see README, 'What starts on its own'"
}

# --- snapshot packages: copy what is missing, never overwrite --------------------------------------------------
SNAPSHOTS=(claude codex git npm rtk opencode gemini ranger nvim desktop)

step_snapshots() {
  local pkg file dest copied=0 differ=0
  for pkg in "${SNAPSHOTS[@]}"; do
    while IFS= read -r file; do
      dest="$HOME/${file#"$pkg"/}"
      [[ ${file#"$pkg"/} == .* ]] || continue # a package's own README is not a config file
      [[ -L $REPO/$file ]] && continue # in-repo links are the links step's business
      if [[ ! -e $dest && ! -L $dest ]]; then
        act mkdir -p "$(dirname "$dest")"
        act cp -p "$REPO/$file" "$dest"
        copied=$((copied + 1))
      elif [[ -f $dest ]] && ! same "$REPO/$file" "$dest"; then
        differ=$((differ + 1))
        say "    differs: ~/${dest#"$HOME"/}"
      fi
    done < <(git -C "$REPO" ls-files "$pkg")
  done
  say "  $copied to copy; $differ differ from the snapshot and are left alone (diff them by hand)"
}

# --- hooks and plugins: add what the snapshots define to the live files, keeping everything else ------------------
# For each event, a group with the same matcher gets the missing commands; a new matcher gets the whole group.
# Claude's plugin and marketplace entries (ponytail) are added the same way; the live value wins on a clash.
# shellcheck disable=SC2016 # jq variables, not shell ones
HOOKS_JQ='
($s[0].hooks // {}) as $want
| .hooks = (.hooks // {})
| reduce ($want | to_entries[]) as $ev (.;
    reduce $ev.value[] as $g (.;
      if (.hooks[$ev.key] // [] | any(.matcher == $g.matcher)) then
        .hooks[$ev.key] |= map(
          if .matcher == $g.matcher then
            . as $cur
            | .hooks += ($g.hooks | map(select(.command as $c | ($cur.hooks | map(.command) | index($c)) == null)))
          else . end)
      else
        .hooks[$ev.key] = ((.hooks[$ev.key] // []) + [$g])
      end))
| if $s[0].enabledPlugins then .enabledPlugins = ($s[0].enabledPlugins + (.enabledPlugins // {})) else . end
| if $s[0].extraKnownMarketplaces then .extraKnownMarketplaces = ($s[0].extraKnownMarketplaces + (.extraKnownMarketplaces // {})) else . end'

merge_hooks() { # merge_hooks <snapshot in the repo> <live file under $HOME>
  local snap="$REPO/$1" live="$HOME/$2" merged
  if [[ ! -f $live ]]; then say "  ~/$2 is missing: the snapshots step copies it"; return 0; fi
  merged=$(jq --slurpfile s "$snap" "$HOOKS_JQ" "$live")
  if [[ $(jq -S . <<<"$merged") == "$(jq -S . "$live")" ]]; then say "  ~/$2 already has the hooks"; return 0; fi
  say "  ~/$2 gains the hooks and plugins it lacks (a copy is kept as $2.bak-install)"
  if ((APPLY)); then
    cp -p "$live" "$live.bak-install"
    printf '%s\n' "$merged" >"$live"
  fi
}

step_hooks() {
  if ! have jq; then say "  jq is missing: run the apt step first"; return 0; fi
  merge_hooks claude/.claude/settings.json .claude/settings.json
  merge_hooks codex/.codex/hooks.json .codex/hooks.json
  say "  Codex asks you to trust new hooks: open it and run /hooks"
}

# --- the pre-commit hook that keeps this repository public-facing -----------------------------------------------
step_githooks() {
  if [[ $(git -C "$REPO" config core.hooksPath 2>/dev/null || true) == .githooks ]]; then
    say "  core.hooksPath is already .githooks"
  else
    act git -C "$REPO" config core.hooksPath .githooks
  fi
  if [[ ! -f $HOME/.config/dotfiles/private-terms.txt ]]; then
    say "  no ~/.config/dotfiles/private-terms.txt: list the names that must never be committed, one per line"
  fi
}

# --- the hourly Codex model-catalog refresh ------------------------------------------------------------------
step_cron() {
  # shellcheck disable=SC2016 # $HOME stays literal: cron expands it
  local line='17 * * * * $HOME/.codex/model-catalogs/refresh.sh >/dev/null 2>>$HOME/.codex/model-catalogs/refresh.err'
  if [[ ! -x $HOME/.codex/model-catalogs/refresh.sh ]]; then say "  no refresh.sh yet; run the snapshots step first"; return 0; fi
  if crontab -l 2>/dev/null | grep -qF 'model-catalogs/refresh.sh'; then
    say "  already in the crontab"
  else
    act bash -c "(crontab -l 2>/dev/null; echo '$line') | crontab -"
  fi
}

# --- checks that never source credentials ---------------------------------------------------------------------
step_check() {
  zsh -n "$REPO/shell/.zshrc" && bash -n "$REPO/shell/.bashrc" && say "  shell syntax ok"
  python3 -B "$REPO/tests/test_shell_startup.py" || say "  startup test failed: a tool it needs is probably missing"
  # what a tool or installer wrote into a linked file since the last commit, before anyone stages it
  python3 -B "$REPO/tests/check_public.py" --changed && say "  nothing uncommitted breaks the public-facing rules"
}

STEPS=(apt tools uvtools npm links systemd snapshots hooks githooks cron check)
selected=()
for arg in "$@"; do
  case $arg in
    --apply) APPLY=1 ;;
    -h | --help) sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) [[ " ${STEPS[*]} " == *" $arg "* ]] || { say "unknown step: $arg (steps: ${STEPS[*]})"; exit 2; }; selected+=("$arg") ;;
  esac
done
((${#selected[@]})) || selected=("${STEPS[@]}")

for step in "${selected[@]}"; do
  say "== $step"
  "step_$step"
done

say
if ((CONFLICTS)); then say "conflicts above were left alone"; fi
if ((APPLY)); then
  say "done. By hand: ~/.config/shell/secrets.local.sh, the harness logins, 'sudo tailscale up', and the Windows side (README)."
else
  say "dry run: nothing was changed. Re-run with --apply."
fi
exit "$CONFLICTS"

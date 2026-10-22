# Zsh-specific interactive options, completion and prompt.
[[ -o interactive ]] || return 0
[[ ! -r "$HOME/.config/shell/env.sh" ]] || source "$HOME/.config/shell/env.sh"
[[ ! -r "$HOME/.config/shell/aliases.sh" ]] || source "$HOME/.config/shell/aliases.sh"

setopt AUTO_CD AUTO_PUSHD APPEND_HISTORY HIST_IGNORE_DUPS HIST_IGNORE_SPACE
setopt SHARE_HISTORY PUSHD_SILENT EXTENDED_GLOB
HISTFILE="$HOME/.zsh_history"
HISTSIZE=10000
SAVEHIST=10000
HIST_STAMPS="yyyy-mm-dd"

[[ ! -d "$HOME/.grok/completions/zsh" ]] || fpath=("$HOME/.grok/completions/zsh" $fpath)
zstyle ':completion:*' menu select
zstyle ':completion:*' file-sort name
zstyle ':completion:*' list-dirs local

# Autocomplete owns compinit and its widgets; use native completion if absent.
if [[ -r "$HOME/.local/share/zsh/plugins/zsh-autocomplete/zsh-autocomplete.plugin.zsh" ]]; then
    source "$HOME/.local/share/zsh/plugins/zsh-autocomplete/zsh-autocomplete.plugin.zsh"
else
    autoload -Uz compinit
    compinit
fi
bindkey '^r' history-incremental-search-backward

if [[ -r "$HOME/lib/oracle-cli/lib/python3.12/site-packages/oci_cli/bin/oci_autocomplete.sh" ]]; then
    autoload -Uz bashcompinit
    bashcompinit
    source "$HOME/lib/oracle-cli/lib/python3.12/site-packages/oci_cli/bin/oci_autocomplete.sh"
fi
[[ ! -s "$HOME/.bun/_bun" ]] || source "$HOME/.bun/_bun"

if (( $+commands[starship] )); then
    eval "$(starship init zsh)"
fi
if [[ "$TERM" == xterm-ghostty && -n "$WSL_DISTRO_NAME" && -r "$HOME/.local/share/ghostty/shell-integration/zsh/ghostty-integration" ]]; then
    source "$HOME/.local/share/ghostty/shell-integration/zsh/ghostty-integration"
fi

# Autocomplete creates widgets at first precmd; highlighting must load after them.
if [[ -r "$HOME/.local/share/zsh/plugins/zsh-syntax-highlighting/zsh-syntax-highlighting.zsh" ]]; then
    autoload -Uz add-zsh-hook
    _dotfiles_load_highlighting() {
        add-zsh-hook -d precmd _dotfiles_load_highlighting
        source "$HOME/.local/share/zsh/plugins/zsh-syntax-highlighting/zsh-syntax-highlighting.zsh"
        unfunction _dotfiles_load_highlighting
    }
    add-zsh-hook precmd _dotfiles_load_highlighting
fi

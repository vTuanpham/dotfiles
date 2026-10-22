# Ubuntu's global zshrc otherwise runs compinit before zsh-autocomplete.
if [[ -r "$HOME/.local/share/zsh/plugins/zsh-autocomplete/zsh-autocomplete.plugin.zsh" ]]; then
    skip_global_compinit=1
fi

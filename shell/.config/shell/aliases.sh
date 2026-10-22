# Interactive commands shared by Bash and Zsh.
alias ll='ls -la'
alias gs='git status'
alias ga='git add .'
alias gc='git commit -m'
alias gp='git push'
alias ..='cd ..'
alias ...='cd ../..'
alias n='npm'
alias d='docker'
alias py='python'
alias pir='pip install -r requirements.txt'
alias clearCache='find ~/.cache/ -type f -atime +30 -delete'

# A function keeps arguments on Ranger and changes directory only after success.
unalias ranger 2>/dev/null || :
ranger() {
    local ranger_destination
    command ranger --choosedir="$HOME/.rangerdir" "$@" || return
    [ -r "$HOME/.rangerdir" ] || return 0
    ranger_destination=$(cat "$HOME/.rangerdir") || return
    if [ -n "$ranger_destination" ] && [ -d "$ranger_destination" ]; then
        cd -- "$ranger_destination" || return
    fi
}

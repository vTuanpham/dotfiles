# Interactive Bash settings. Scripts and remote commands remain quiet.
case $- in
    *i*) ;;
    *) return ;;
esac

[ ! -r "$HOME/.config/shell/env.sh" ] || . "$HOME/.config/shell/env.sh"
[ ! -r "$HOME/.config/shell/aliases.sh" ] || . "$HOME/.config/shell/aliases.sh"

HISTCONTROL=ignoreboth
HISTSIZE=1000
HISTFILESIZE=2000
shopt -s histappend checkwinsize

if command -v dircolors >/dev/null 2>&1; then
    if [ -r "$HOME/.dircolors" ]; then
        eval "$(dircolors -b "$HOME/.dircolors")"
    else
        eval "$(dircolors -b)"
    fi
    alias ls='ls --color=auto'
    alias grep='grep --color=auto'
    alias fgrep='fgrep --color=auto'
    alias egrep='egrep --color=auto'
fi
alias ll='ls -alF'
alias la='ls -A'
alias l='ls -CF'
[ ! -r "$HOME/.bash_aliases" ] || . "$HOME/.bash_aliases"

if [ -x /usr/bin/lesspipe ]; then
    eval "$(SHELL=/bin/sh lesspipe)"
fi
if ! shopt -oq posix; then
    if [ -r /usr/share/bash-completion/bash_completion ]; then
        . /usr/share/bash-completion/bash_completion
    elif [ -r /etc/bash_completion ]; then
        . /etc/bash_completion
    fi
fi

# Expose nvm without silently switching the inherited Node executable.
if [ -s "$NVM_DIR/nvm.sh" ] && ! command -v nvm >/dev/null 2>&1; then
    . "$NVM_DIR/nvm.sh" --no-use
fi
if [ -x /home/linuxbrew/.linuxbrew/bin/brew ] && [ -z "${HOMEBREW_PREFIX-}" ]; then
    eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv)"
fi
if [ -r "$HOME/lib/oracle-cli/lib/python3.12/site-packages/oci_cli/bin/oci_autocomplete.sh" ]; then
    . "$HOME/lib/oracle-cli/lib/python3.12/site-packages/oci_cli/bin/oci_autocomplete.sh"
fi

bind 'set show-all-if-ambiguous on'
bind 'set show-all-if-unmodified on'
bind 'set completion-ignore-case on'
bind 'set completion-map-case on'

if command -v starship >/dev/null 2>&1; then
    eval "$(starship init bash)"
else
    PS1='\u@\h:\w\$ '
fi

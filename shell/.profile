# Shared login environment. Zsh reads .zprofile, not this file.
[ ! -r "$HOME/.config/shell/env.sh" ] || . "$HOME/.config/shell/env.sh"
if [ -n "${BASH_VERSION-}" ]; then
    case $- in
        *i*) [ ! -r "$HOME/.bashrc" ] || . "$HOME/.bashrc" ;;
    esac
fi

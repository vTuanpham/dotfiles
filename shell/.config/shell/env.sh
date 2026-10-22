# Shared environment for Bash and Zsh; preserve inherited WSL and project paths.
export STARSHIP_CONFIG="$HOME/.config/starship.toml"
export NVM_DIR="$HOME/.nvm"
export NPM_CONFIG_PREFIX="$HOME/.npm-global"
export BUN_INSTALL="$HOME/.bun"
export GOPATH="$HOME/.local/share/go"
export GOMODCACHE="$HOME/.cache/go/mod"
export GENSIM_DATA_DIR="$HOME/.cache/gensim"
export NLTK_DATA="$HOME/.local/share/nltk_data"

# shortcut: bundled Node roots miss emergency CA removals; remove after patched runtimes are installed.
case " ${NODE_OPTIONS-} " in
    *" --use-openssl-ca "*) ;;
    *) export NODE_OPTIONS="${NODE_OPTIONS:+$NODE_OPTIONS }--use-openssl-ca" ;;
esac

[ ! -r "$HOME/.local/bin/env" ] || . "$HOME/.local/bin/env"
[ ! -r "$HOME/.cargo/env" ] || . "$HOME/.cargo/env"
[ ! -r "$HOME/.cuda_paths" ] || . "$HOME/.cuda_paths"

_dotfiles_prepend_path() {
    [ -d "$1" ] || return 0
    case ":${PATH-}:" in
        *:"$1":*) ;;
        *) PATH="$1${PATH:+:$PATH}" ;;
    esac
}

for dotfiles_directory in \
    "$HOME/.npm-global/bin" \
    "$HOME/.local/share/nvim/mason/bin" \
    "$HOME/.opencode/bin" \
    "$HOME/lib/oracle-cli/bin" \
    "$HOME/bin" \
    "$GOPATH/bin" \
    "$HOME/.grok/bin" \
    "$HOME/.bun/bin" \
    "$HOME/.kimi-code/bin" \
    "$HOME/.local/bin"
do
    _dotfiles_prepend_path "$dotfiles_directory"
done
export PATH
unset dotfiles_directory
unset -f _dotfiles_prepend_path

# Private file lives outside Git; shell exports use no separate dotenv parser.
[ ! -r "$HOME/.config/shell/secrets.local.sh" ] || . "$HOME/.config/shell/secrets.local.sh"

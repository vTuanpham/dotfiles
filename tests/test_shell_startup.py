"""Check Bash/Zsh startup without launching apps or printing credentials."""

import os
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[1]
shell_root = root / "shell"
checks = r'''
if [ -n "${ZSH_VERSION-}" ]; then
    for shell_prompt_hook in "${precmd_functions[@]}"; do "$shell_prompt_hook"; done
    command -v _zsh_highlight >/dev/null || exit 33
fi
shell_expected_pwd=$PWD
shell_original_path=$PATH
shell_original_node_options=${NODE_OPTIONS-}
case ":$PATH:" in *:"$DOTFILES_TEST_SENTINEL":*) ;; *) exit 21 ;; esac
command -v node >/dev/null || exit 22
command -v ranger >/dev/null || exit 23
command -v rtk >/dev/null || exit 24
command -v starship >/dev/null || exit 25
. "$DOTFILES_TEST_RC" || exit 26
if [ -n "${ZSH_VERSION-}" ]; then
    for shell_prompt_hook in "${precmd_functions[@]}"; do "$shell_prompt_hook"; done
    [[ -n ${widgets[menu-search]-} && -n ${widgets[recent-paths]-} ]] || exit 34
fi
[ "$PWD" = "$shell_expected_pwd" ] || exit 27
[ "$PATH" = "$shell_original_path" ] || exit 28
[ "${NODE_OPTIONS-}" = "$shell_original_node_options" ] || exit 35
case " ${NODE_OPTIONS-} " in *" --use-openssl-ca "*) ;; *) exit 36 ;; esac
case ":$PATH:" in *:"$DOTFILES_TEST_SENTINEL":*) ;; *) exit 29 ;; esac
alias gs >/dev/null || exit 30
command -v ranger >/dev/null || exit 31
[ "$CUDA_HOME" = /usr/local/cuda-12.6 ] || exit 32
printf 'shell startup checks passed\n'
'''

for shell in ("bash", "zsh"):
    rc = shell_root / ("." + shell + "rc")
    environment = os.environ.copy()
    environment["ZDOTDIR"] = str(shell_root)
    environment["DOTFILES_TEST_RC"] = str(rc)
    environment["DOTFILES_TEST_SENTINEL"] = "/tmp/dotfiles-inherited-path"
    environment["PATH"] += ":" + environment["DOTFILES_TEST_SENTINEL"]
    environment["TERM"] = "xterm-256color"
    args = [shell]
    if shell == "bash":
        args += ["--rcfile", str(rc)]
    args += ["-i", "-c", checks]
    result = subprocess.run(args, env=environment, cwd="/tmp", capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, shell + " startup check failed: " + str(result.returncode)
    assert "shell startup checks passed" in result.stdout
    assert "Hello" not in result.stdout and "Reloading" not in result.stdout
    assert "unhandled ZLE widget" not in result.stderr, "Zsh plugin widget initialization failed"
    quiet = subprocess.run([shell, "-c", '. "$DOTFILES_TEST_RC"'], env=environment, capture_output=True, text=True, timeout=10)
    assert quiet.returncode == 0 and quiet.stdout == "" and quiet.stderr == "", shell + " non-interactive startup was not quiet"
    print(shell + ": reload preserves cwd/PATH, required tools resolve, non-interactive startup is quiet")

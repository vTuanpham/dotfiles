# ghostty

[← Packages](../README.md#packages) · **Snapshot** · not in `install.sh`; copy by hand

Zsh shell integration from [Ghostty](https://ghostty.org), at
`.local/share/ghostty/shell-integration/zsh/`, used by the GhostInTheWSL terminal (see `windows/`).
`shell/.zshrc` sources it from `~/.local/share/ghostty/...` only when `TERM` is `xterm-ghostty` inside WSL.

The integration script is Ghostty's, under the **GPL-3.0**; its license text sits beside it
(`LICENSE.GPL-3`) and applies to that file, not to the rest of this repository.

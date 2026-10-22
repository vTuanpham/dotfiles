# starship

[← Packages](../README.md#packages) · **Live** · `./install.sh --apply links`

The shared [Starship](https://starship.rs) prompt, `.config/starship.toml`, linked to
`~/.config/starship.toml`; Zsh, Bash and the Claude status line all read it.

Windows PowerShell reads this tracked file directly through `STARSHIP_CONFIG` pointing at
`\\wsl$\<distro>\home\<user>\dotfiles\starship\.config\starship.toml`; Windows cannot follow the Stow
symlink, so use the tracked path. WSL stays the owner and there is no Windows copy.

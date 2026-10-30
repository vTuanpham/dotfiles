# starship

[← Packages](../README.md#packages) · **Live** · `./install.sh --apply links`

The shared [Starship](https://starship.rs) prompt, `.config/starship.toml`, linked to
`~/.config/starship.toml`; Zsh, Bash and the Claude status line all read it.

<img src="docs/prompt.svg" alt="Two drawn prompts in the Gruvbox Dark palette. The first shows operating system and user, shell, directory, Git branch and status, Node.js version and time after a successful command. The second shows a failed command in a folder without a repository or language: the separators stay and leave thin color bands." width="100%">

Left to right: operating system and user, shell, directory, Git, language, Docker or
Conda, time. Modules appear only where Starship finds something to show, but the
separators are part of the format, so an absent module leaves a thin color band. The
last command's status colors the chevron on the second line (green on success, red on
failure; Vi replace and visual modes have their own colors).

| Segment | Section | Notes |
| --- | --- | --- |
| OS, user | `[os]`, `[username]` | Always shown; the user is not hidden over SSH or as root |
| Shell | `[shell]` | Custom indicators: Zsh `𐰁sh`, Bash `ᛒash`, PowerShell `_`, fish `󰈺` |
| Directory | `[directory]` | Last three folders, `…/` for the rest; `Documents`, `Downloads`, `Music`, `Pictures`, `Developer` become icons |
| Git | `[git_branch]`, `[git_status]` | Branch and status symbols |
| Language | `[c]`, `[rust]`, `[golang]`, `[nodejs]`, `[php]`, `[java]`, `[kotlin]`, `[haskell]`, `[python]` | One shared blue segment with the version; Python adds its virtualenv |
| Environment | `[docker_context]`, `[conda]` | Grey segment |
| Time | `[time]` | 24-hour `%R` |

The preview uses **SauceCodePro NFP SemiBold, 12 pt**, matching the
[terminal configuration](../windows/README.md). Prompt icons need a Nerd Font;
the `gruvbox_dark` palette is defined in `starship.toml`.

Windows PowerShell reads this tracked file directly through `STARSHIP_CONFIG` pointing at
`\\wsl$\<distro>\home\<user>\dotfiles-with-agency\starship\.config\starship.toml`; Windows cannot follow the Stow
symlink, so use the tracked path. WSL stays the owner and there is no Windows copy.

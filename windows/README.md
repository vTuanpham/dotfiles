# windows

[← Packages](../README.md#packages) · **Manual** · not installed by `install.sh`

Windows-side terminal config. **Not Stowed and not linked**: copy by hand, and
exclude this package from home-directory Stow commands. The snapshots assume a
WSL distro named `Ubuntu`; change the distro and home path for your machine.

## Terminal configuration

Windows PowerShell reads the shared Starship configuration directly from
`\\wsl$\<distro>\home\<user>\dotfiles\starship\.config\starship.toml` through
`STARSHIP_CONFIG` in its profile. Use that tracked file rather than the
`~/.config/starship.toml` Stow symlink: Windows cannot resolve that symlink on
this machine. WSL remains the configuration owner; no Windows copy is needed.

| Repository file | Windows destination |
| --- | --- |
| `windows/ghostinthewsl/config.ghostinthewsl` | Beside the GhostInTheWSL executable (wherever you unpacked it) |
| `windows/windows-terminal/settings.json` | Windows Terminal's `LocalState\settings.json`; normally beneath `%LOCALAPPDATA%\Packages\Microsoft.WindowsTerminal_8wekyb3d8bbwe` |

Install the SauceCodePro Nerd Font Propo SemiBold face in Windows. Ghost lists
the same face as `SauceCodePro NFP SemiBold`. Open Ghost's config with `Ctrl+Shift+,`; reload it through the `Ctrl+Shift+P`
command palette. Restart Ranger after changing its plugin files.

Ghost starts new windows and tabs in your WSL home (`/home/<user>`, set in `working-directory`),
rather than the executable's Downloads folder. Use the explicit WSL path: this Windows build's
`home` option resolves the Windows user's home. Directory inheritance is disabled
for windows; this build also uses that setting when creating tabs. Explicit
launch directory overrides still take precedence. Shell startup preserves the
directory supplied by its caller.

Ranger previews images inline only in Ghost/WSL outside tmux. Enter on
image/audio/video files opens the Windows default application in WSL. Windows
Photos may prompt before opening a file through the WSL network path.

The limited Alt-key workaround lives only in the Ghost config. It sends a
physical Escape chord and consumes duplicate translated text; it does not
install an OS keyboard remap. Live window size/opacity adjustments are not
persisted by these config snapshots.

Ghost matches Windows Terminal's Ctrl+C/Ctrl+V behavior: Ctrl+C copies selected
text as plain text and otherwise passes through to the application; Ctrl+V
pastes from the clipboard. Ctrl+Shift+C and Ctrl+Insert also copy plain text;
copying clears the selection. Right-click copies a selection or pastes when
nothing is selected. Ctrl+Shift+V remains available.

Windows-style shortcuts in Ghost close the active pane with Ctrl+Shift+W,
navigate panes with Alt+arrows, resize with Alt+Shift+arrows, and select tabs
with Ctrl+Alt+1–9. Both physical and translated Alt+number bindings are removed
so those keys reach applications. Ctrl+Shift+PageUp/Down scroll one page.
Ctrl+Shift+, opens the config file; reload configuration through the
Ctrl+Shift+P command palette. Existing Ghost pane-navigation/resize aliases
remain available.

Ghost's default Ctrl+Enter fullscreen and Ctrl+Shift+Enter split-zoom shortcuts
are unbound so applications can receive modified Enter using their negotiated
input protocol. These actions remain available in the command palette. For
other conflicts, use `keybind = <shortcut>=unbind` rather than `ignore`, which
discards input, or a fixed escape sequence that bypasses protocol negotiation.
Other terminal shortcuts remain enabled; inspect this fork's effective list with
`ghostinthewsl-v0.1.5.exe +list-keybinds` before changing them.

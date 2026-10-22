# ranger

[← Packages](../README.md#packages) · **Snapshot** · `./install.sh --apply snapshots`

`~/.config/ranger`:

- `rc.conf`: sets the `devicons` line mode.
- `plugins/ranger_devicons/`: the file-type icons, vendored with its license files from
  [ranger-devicons](https://github.com/alexanderjeurissen/ranger_devicons) at revision
  `a8d626485ca83719e1d8d5e32289cd96a097c861`.
- `plugins/wsl_media.py`: inline image previews in Ghost/WSL outside tmux, and opening images, audio and
  video with the Windows default application (needs `powershell.exe` and `wslpath`).
- `tests/test_wsl_media.py`: the plugin's check, run with `python3 -B ranger/.config/ranger/tests/test_wsl_media.py`.

Needs Ranger, `kitten` and ImageMagick; restart Ranger after changing a plugin.

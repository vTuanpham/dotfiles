# nvim

[← Packages](../README.md#packages) · **Snapshot** · `./install.sh --apply snapshots`

`~/.config/nvim`: a [LazyVim](https://www.lazyvim.org) setup. The directory has its own
`README.md` and `LICENSE` from the LazyVim starter.

- `init.lua`, `lua/config/`: bootstrap, options, keymaps and autocmds.
- `lua/plugins/`: one file per plugin spec or tweak (dashboard, lualine, image and terminal-image support for
  Ghost/WSL, a smear cursor, and others).
- `lazy-lock.json`: the plugin versions, so a restore gets the same ones.
- `lazyvim.json`, `stylua.toml`, `.neoconf.json`: LazyVim extras and formatter settings.

Plugins are installed by Neovim on first start. Image previews rely on `ImageMagick`, `ffmpeg` and `pdftoppm`.
The dashboard greeting is in `lua/plugins/dashboard.lua`.

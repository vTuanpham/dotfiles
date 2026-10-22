-- Options are automatically loaded before lazy.nvim startup
-- Default options that are always set: https://github.com/LazyVim/LazyVim/blob/main/lua/lazyvim/config/options.lua
-- Add any additional options here

local opt = vim.opt

-- Wsl Clipboard
if vim.fn.has("wsl") == 1 then
  opt.clipboard = {
    name = "WslClipboard",
    copy = {
      ["+"] = "clip.exe",
      ["*"] = "clip.exe",
    },
    paste = {
      ["+"] = 'powershell.exe -c [Console]::Out.Write($(Get-Clipboard -Raw).tostring().replace("\r\n", "\n"))',
      ["*"] = 'powershell.exe -c [Console]::Out.Write($(Get-Clipboard -Raw).tostring().replace("\r\n", "\n"))',
    },
    cache_enabled = 0,
  }
end

-- Use Pyright
vim.g.lazyvim_python_lsp = "pyright"

-- Use snacks picker instead of fzf (fzf version too old)
vim.g.lazyvim_picker = "snacks"

-- Keep the configured Neo-tree dashboard action and workflow.
vim.g.lazyvim_explorer = "neo-tree"

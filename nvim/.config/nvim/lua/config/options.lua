-- Options are automatically loaded before lazy.nvim startup
-- Default options that are always set: https://github.com/LazyVim/LazyVim/blob/main/lua/lazyvim/config/options.lua
-- Add any additional options here

-- Windows pipes need UTF-8 explicitly; clip.exe otherwise guesses a legacy code page.
if vim.fn.has("wsl") == 1 then
  local copy = {
    "powershell.exe",
    "-NoLogo",
    "-NoProfile",
    "-NonInteractive",
    "-Command",
    "[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false); Set-Clipboard -Value ([Console]::In.ReadToEnd())",
  }
  local paste = {
    "powershell.exe",
    "-NoLogo",
    "-NoProfile",
    "-NonInteractive",
    "-Command",
    '[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); [Console]::Out.Write(([string](Get-Clipboard -Raw)).Replace("`r`n", "`n"))',
  }
  vim.g.clipboard = {
    name = "WslClipboard",
    copy = {
      ["+"] = copy,
      ["*"] = copy,
    },
    paste = {
      ["+"] = paste,
      ["*"] = paste,
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

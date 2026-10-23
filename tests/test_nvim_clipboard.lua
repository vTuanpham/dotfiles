-- Run with nvim --headless -u NONE -i NONE -l tests/test_nvim_clipboard.lua.
local has = vim.fn.has
vim.fn.has = function(feature)
  return feature == "wsl" and 0 or has(feature)
end
dofile("nvim/.config/nvim/lua/config/options.lua")
assert(vim.g.clipboard == nil, "must leave other platforms' clipboard alone")
vim.fn.has = function(feature)
  return feature == "wsl" and 1 or has(feature)
end
dofile("nvim/.config/nvim/lua/config/options.lua")
vim.fn.has = has
local clipboard = vim.g.clipboard
assert(clipboard.name == "WslClipboard")
assert(vim.deep_equal(clipboard.copy["+"], clipboard.copy["*"]))
assert(vim.deep_equal(clipboard.paste["+"], clipboard.paste["*"]))

if vim.fn.executable("powershell.exe") == 0 then
  print("Neovim clipboard configuration passed; Windows pipe checks skipped")
  return
end

-- Shadow the clipboard cmdlets so the user's real clipboard is never read or changed.
local sample = "· ảnh 日本語 🔒\nsecond line\n"
local copy = vim.deepcopy(clipboard.copy["+"])
copy[#copy] = "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
  .. "function Set-Clipboard { param($Value) [Console]::Out.Write($Value) }; "
  .. copy[#copy]
local result = vim.system(copy, { stdin = sample, text = true }):wait(20000)
assert(result.code == 0, result.stderr)
assert(result.stdout == sample, "copy corrupted Unicode or newlines")

local paste = vim.deepcopy(clipboard.paste["+"])
paste[#paste] = 'function Get-Clipboard { param([switch]$Raw) "· ảnh 日本語 🔒`r`nsecond line`r`n" }; '
  .. paste[#paste]
result = vim.system(paste, { text = true }):wait(20000)
assert(result.code == 0, result.stderr)
assert(result.stdout == sample, "paste corrupted Unicode or newlines")
paste[#paste] = "function Get-Clipboard { param([switch]$Raw) $null }; " .. clipboard.paste["+"][6]
result = vim.system(paste, { text = true }):wait(20000)
assert(result.code == 0 and result.stdout == "", "empty clipboard must paste cleanly")
print("Neovim clipboard checks passed: platform scope, Unicode copy/paste, newlines and empty text")

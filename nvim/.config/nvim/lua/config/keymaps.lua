-- Keymaps are automatically loaded on the VeryLazy event
-- Default keymaps that are always set: https://github.com/LazyVim/LazyVim/blob/main/lua/lazyvim/config/keymaps.lua
-- Add any additional keymaps here

-- Map for Menu

-- Keyboard menu mapping
vim.keymap.set("n", "<C-t>", function()
  require("menu").open("default")
end, {})

-- Mouse menu mapping + nvim-tree
vim.keymap.set("n", "<RightMouse>", function()
  vim.cmd.exec('"normal! \\<RightMouse>"')

  local options = vim.bo.ft == "NvimTree" and "nvimtree" or "default"
  require("menu").open(options, { mouse = true })
end, {})

-- Keymap for clipboard operations
vim.keymap.set("v", "<C-c>", '"+y', { noremap = true, silent = true, desc = "Copy to system clipboard" })
vim.keymap.set(
  "i",
  "<C-v>",
  "<C-r>+",
  { noremap = true, silent = true, desc = "Paste from system clipboard (Insert mode)" }
)
vim.keymap.set(
  "n",
  "<C-v>",
  '"+p',
  { noremap = true, silent = true, desc = "Paste from system clipboard (Normal Mode)" }
)
vim.keymap.set("v", "<C-x>", '"+d', { noremap = true, silent = true, desc = "Cut to system clipboard" })

-- Ctrl + / to comment
vim.keymap.set("n", "<C-_>", function()
  local line = vim.fn.line(".")
  require("mini.comment").toggle_lines(line, line)
end, { noremap = true, silent = true, desc = "Comment current line" })
vim.keymap.set("x", "<C-_>", function()
  local first, last = vim.fn.line("v"), vim.fn.line(".")
  require("mini.comment").toggle_lines(math.min(first, last), math.max(first, last))
end, { noremap = true, silent = true, desc = "Comment selection" })

-- Save and quit to Dashboard or quit to Dashboard
vim.api.nvim_create_user_command("Wd", function()
  -- Save the current file, then go to the dashboard (for alpha-nvim)
  vim.cmd("w") -- save the file
  vim.cmd("Dashboard") -- or 'Dashboard' if using dashboard-nvim
end, {})

vim.api.nvim_create_user_command("D", function()
  -- Quit the current file, then go to the dashboard (for alpha-nvim)
  vim.cmd("Dashboard") -- or 'Dashboard' if using dashboard-nvim
end, {})

-- Keymap for creating new directories
local mkdir = require("utils.mkdir")
vim.keymap.set("n", "<leader>nd", mkdir.create_directory, { desc = "Create new directory in cwd" })

-- Keymap for making a new file
local file = require("utils.file")
vim.keymap.set("n", "<leader>nf", file.create_file, { desc = "Create new file in cwd" })

-- Keymap for undo to last saved state
vim.keymap.set("n", "U", ":earlier 1f<CR>")

-- Keymap for wormhole
vim.keymap.set("n", "<leader>wl", "<Plug>(WormholeLabels)", { desc = "Wormhole Labels" })
vim.keymap.set(
  "n",
  "<Esc>",
  "<Plug>(WormholeCloseLabels)",
  { desc = "Wormhole Close Labels", noremap = true, silent = true }
)

-- Keymap for esc to normal mode in terminal mode
vim.keymap.set(
  "t",
  "<Esc><Esc>",
  [[<C-\><C-n>]],
  { noremap = true, silent = true, desc = "Esc to normal mode in terminal" }
)

-- Keymap for opening a floating diagnostic error window
vim.keymap.set(
  "n",
  "<leader>df",
  vim.diagnostic.open_float,
  { noremap = true, silent = true, desc = "Open floating diagnostic window" }
)

-- Keymap shorthand for opening terminal in the vertical split
vim.keymap.set("n", "<leader>TV", function()
  vim.cmd("vsplit | terminal")
end, { desc = "Open terminal in vertical split", noremap = true, silent = true })

-- Keymap shorthand for opening terminal in the horizontal split
vim.keymap.set("n", "<leader>TH", function()
  vim.cmd("split | terminal")
end, { desc = "Open terminal in horizontal split", noremap = true, silent = true })

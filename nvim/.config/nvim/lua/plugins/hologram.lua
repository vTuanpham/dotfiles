return {
  {
    "vhyrro/hologram.nvim",
    cond = function()
      local is_headless = vim.env.NVIM_HEADLESS == "1" or vim.env.TERM == "dumb" or vim.v.vim_did_enter == 0
      return not is_headless
    end,
    config = function()
      local ok, err = pcall(require("hologram").setup, {
        auto_display = true,
      })
      if not ok then
        vim.notify("Hologram failed to load: " .. err, vim.log.levels.WARN)
      end
    end,
  },
}

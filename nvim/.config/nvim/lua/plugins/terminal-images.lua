return {
  {
    "folke/snacks.nvim",
    opts = function(_, opts)
      if vim.env.WSL_DISTRO_NAME and vim.env.TERM == "xterm-ghostty" then
        opts.image = vim.tbl_deep_extend("force", opts.image or {}, { enabled = true })
        -- The Windows renderer cannot read Linux filenames; send image bytes.
        for _, environment in ipairs(require("snacks.image.terminal").envs()) do
          if environment.name == "ghostty" then
            environment.env = { TERM = "^xterm%-ghostty$" }
            environment.remote = true
          end
        end
      end
    end,
  },
  { "vhyrro/hologram.nvim", enabled = not (vim.env.WSL_DISTRO_NAME and vim.env.TERM == "xterm-ghostty") },
}

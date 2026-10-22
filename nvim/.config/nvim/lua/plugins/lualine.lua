return {
  {
    "nvim-lualine/lualine.nvim",
    opts = function(_, opts)
      local function get_timerly_status()
        local state = require("timerly.state")
        if state.progress == 0 then
          return ""
        end

        local total = math.max(0, state.total_secs + 1) -- Add 1 to sync with timer display
        local mins = math.floor(total / 60)
        local secs = total % 60

        return string.format("%s %02d:%02d", state.mode:gsub("^%l", string.upper), mins, secs)
      end

      table.insert(opts.sections.lualine_x, get_timerly_status)
    end,
  },
}

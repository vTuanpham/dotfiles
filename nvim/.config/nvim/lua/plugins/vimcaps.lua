return {
  {
    "suxpert/vimcaps",
    build = function()
      -- On Linux, compile the library manually
      vim.fn.system("make")
    end,
    config = function()
      -- Any additional setup or configuration for vimcaps can go here
    end,
  },
}

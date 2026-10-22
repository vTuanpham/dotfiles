local model_config = require("config.models").dashboard
local FACT_TITLE_MARKER = "__NVIM_RANDOM_FACT_TITLE__"
local FACT_BODY_MARKER = "__NVIM_RANDOM_FACT_BODY__"

return {
  "nvimdev/dashboard-nvim",
  opts = function()
    local logo = [[
          	  		                Welcome to my workspace!                                        Z
                                                                                                      
Z 

         ______   __  __     ______     __   __        ______   __  __     ______     __    __       Z    
     /\__  _\ /\ \/\ \   /\  __ \   /\ "-.\ \      /\  == \ /\ \_\ \   /\  __ \   /\ "-./  \     z  
     \/_/\ \/ \ \ \_\ \  \ \  __ \  \ \ \-.  \     \ \  _-/ \ \  __ \  \ \  __ \  \ \ \-./\ \  z   
   \ \_\  \ \_____\  \ \_\ \_\  \ \_\\"\_\     \ \_\    \ \_\ \_\  \ \_\ \_\  \ \_\ \ \_\
    \/_/   \/_____/   \/_/\/_/   \/_/ \/_/      \/_/     \/_/\/_/   \/_/\/_/   \/_/  \/_/
]]

    local function config()
      vim.cmd.cd(vim.fn.stdpath("config"))
      require("persistence").load()
    end

    -- stylua: ignore start
    local function restore_session() require("persistence").load() end
    local function restore_last_session() require("persistence").load({ last = true }) end
    local function quit() vim.api.nvim_input("<cmd>qa<cr>") end
    -- stylua: ignore end

    local function fetch_random_fact(callback)
      local function wrap_text(text, width)
        local lines = {}
        local line = ""
        for word in text:gmatch("%S+") do
          if #line + #word + 1 > width then
            table.insert(lines, line)
            line = word
          else
            if #line > 0 then
              line = line .. " " .. word
            else
              line = word
            end
          end
        end
        if #line > 0 then
          table.insert(lines, line)
        end
        return lines
      end

      math.randomseed(os.time())
      local domain_list = {
        "science", "history", "technology", "culture", "art", "nature",
        "space", "food", "animals", "mythology", "sports", "literature", "geography",
      }
      local domain = domain_list[math.random(#domain_list)]
      local system_prompt = "Give one accurate, lesser-known fact about the topic. "
        .. "Prefer well-established facts; don't guess or invent citations. "
        .. "Return only the fact in one or two short plain-text sentences."
      local prompt = "Topic: " .. domain .. ". Give one surprising fact."

      local provider = model_config.provider
      local model = model_config.models[provider]
      local key_name = ({ google = "GOOGLE_API_KEY", cerebras = "CEREBRAS_API_KEY" })[provider]
      local metadata = { provider = provider, model = model, domain = domain }
      local function finish(fact, err)
        vim.schedule(function()
          if fact then
            fact = wrap_text(fact, math.max(50, vim.o.columns - 50))
          end
          callback(fact, err, metadata)
        end)
      end

      if not model or not key_name then
        finish(nil, "Invalid dashboard model configuration")
        return
      end

      local api_key = os.getenv(key_name)
      if not api_key or api_key == "" then
        finish(nil, "Set " .. key_name)
        return
      end

      local url, data, auth_header
      if provider == "cerebras" then
        url = "https://api.cerebras.ai/v1/chat/completions"
        auth_header = "Authorization: Bearer " .. api_key
        data = vim.json.encode({
          model = model,
          messages = {
            { role = "system", content = system_prompt },
            { role = "user", content = prompt },
          },
          max_completion_tokens = 256,
        })
      else
        url = "https://generativelanguage.googleapis.com/v1beta/models/" .. model .. ":generateContent"
        auth_header = "x-goog-api-key: " .. api_key
        data = vim.json.encode({
          contents = { parts = { { text = prompt } } },
          system_instruction = { parts = { { text = system_prompt } } },
          generationConfig = {
            maxOutputTokens = 256,
            thinkingConfig = { thinkingLevel = model_config.thinking_level or "low" },
          },
        })
      end

      local function quote_config(value)
        value = value:gsub("\\", "\\\\"):gsub('"', '\\"'):gsub("\n", "\\n"):gsub("\r", "\\r")
        return '"' .. value .. '"'
      end

      local curl_config = table.concat({
        "silent",
        "show-error",
        "fail-with-body",
        "connect-timeout = 3",
        "max-time = 8",
        "header = " .. quote_config("Content-Type: application/json"),
        "header = " .. quote_config(auth_header),
        "data-binary = " .. quote_config(data),
        "url = " .. quote_config(url),
        "",
      }, "\n")

      local started = pcall(
        vim.system,
        { "curl", "--config", "-" },
        { text = true, stdin = curl_config },
        function(result)
          if result.code ~= 0 then
            finish(nil, "Provider unavailable; check the API key or quota")
            return
          end

          local decode_ok, decoded = pcall(vim.json.decode, result.stdout or "")
          if not decode_ok or type(decoded) ~= "table" or type(decoded.error) == "table" then
            finish(nil, "Invalid provider response; check the API key or quota")
            return
          end

          local fact
          if provider == "cerebras" then
            fact = decoded.choices and decoded.choices[1] and decoded.choices[1].message and decoded.choices[1].message.content
          else
            fact = decoded.candidates
              and decoded.candidates[1]
              and decoded.candidates[1].content
              and decoded.candidates[1].content.parts
              and decoded.candidates[1].content.parts[1]
              and decoded.candidates[1].content.parts[1].text
          end

          if type(fact) ~= "string" or fact == "" then
            finish(nil, "Provider returned no fact")
            return
          end
          finish(fact)
        end
      )

      if not started then
        finish(nil, "Could not start curl")
      end
    end

    local mkdir = require("utils.mkdir")
    local mkfile = require("utils.file")

    return {
      _fetch_random_fact = fetch_random_fact,
      logo = logo,
      theme = "doom",
      hide = {
        statusline = false,
      },
      config = {
        center = {
          { action = 'lua LazyVim.pick()()', desc = "Find File", icon = "", key = "f" },
          { action = mkfile.create_file, desc = "New File", icon = "", key = "n" },
          { action = mkdir.create_directory, desc = "New Dir", icon = "", key = "d" },
          { action = "Neotree", desc = "Explorer", icon = "", key = "e" },
          { action = 'lua LazyVim.pick("oldfiles")()', desc = "Recent Files", icon = "", key = "r" },
          { action = 'lua LazyVim.pick("live_grep")()', desc = "Find Text", icon = "", key = "g" },
          { action = config, desc = "Config Session", icon = "", key = "c" },
          { action = 'lua LazyVim.pick.config_files()()', desc = "Config Files", icon = "", key = "C" },
          { action = restore_session, desc = "Restore Session", icon = "󰁯", key = "s" },
          { action = restore_last_session, desc = "Restore Last Session", icon = "󰦛", key = "S" },
          { action = "LazyExtras", desc = "Lazy Extras", icon = "", key = "x" },
          { action = "Lazy", desc = "Lazy", icon = "󰒲", key = "l" },
          { action = quit, desc = "Quit", icon = "", key = "q" },
        },
        footer = function()
          local stats = require("lazy").stats()
          local ms = (math.floor(stats.startuptime * 100 + 0.5) / 100)
          return { "⚡ Neovim loaded " .. stats.loaded .. "/" .. stats.count .. " plugins in " .. ms .. "ms" }
        end,
      },
    }
  end,

  config = function(_, opts)
    local get_random_fact = opts._fetch_random_fact
    opts._fetch_random_fact = nil

    local win_height = vim.api.nvim_win_get_height(0) + 2
    local _, logo_count = string.gsub(opts.logo, "\n", "")
    local logo_height = logo_count + 2
    local actions_height = #opts.config.center * 2 - 1
    local total_height = logo_height + actions_height + 2
    local margin = math.floor((win_height - total_height) / 2)
    if margin - 5 < 0 then
      margin = 5
    elseif margin - 5 > 0 then
      margin = margin - 5
    end
    local logo = string.rep("\n", margin) .. opts.logo .. "\n"

    local function tableMerge(result, ...)
      for _, t in ipairs({ ... }) do
        for _, v in ipairs(t) do
          table.insert(result, v)
        end
      end
    end

    local fact = { FACT_TITLE_MARKER, FACT_BODY_MARKER }

    local fact_height_padding = 11
    local fact_height = #fact
    total_height = logo_height + actions_height + fact_height + fact_height_padding
    margin = math.floor((win_height - total_height) / 2)

    tableMerge(fact, vim.split(string.rep("\n", margin), "\n"))

    local table_logo = vim.split(logo, "\n")
    local final_logo = {}
    tableMerge(final_logo, table_logo, fact)

    opts.config.header = final_logo

    for _, button in ipairs(opts.config.center) do
      button.desc = "  " .. button.desc .. string.rep(" ", 40 - #button.desc)
      button.key_format = "%s"
    end

    if vim.o.filetype == "lazy" then
      vim.api.nvim_create_autocmd("WinClosed", {
        pattern = tostring(vim.api.nvim_get_current_win()),
        once = true,
        callback = function()
          vim.schedule(function()
            vim.api.nvim_exec_autocmds("UIEnter", { group = "dashboard" })
          end)
        end,
      })
    end

    local fact_result
    local request_started = false

    local function dashboard_buffers()
      local buffers = {}
      for _, buf in ipairs(vim.api.nvim_list_bufs()) do
        if vim.api.nvim_buf_is_loaded(buf) and vim.bo[buf].filetype == "dashboard" then
          table.insert(buffers, buf)
        end
      end
      return buffers
    end

    local function replace_marker(buf, marker, replacement, width)
      local lines = vim.api.nvim_buf_get_lines(buf, 0, -1, false)
      for index, line in ipairs(lines) do
        if line:find(marker, 1, true) then
          local centered = {}
          for _, text in ipairs(replacement) do
            local padding = math.max(0, math.floor((width - vim.fn.strdisplaywidth(text)) / 2))
            table.insert(centered, string.rep(" ", padding) .. text)
          end
          vim.api.nvim_buf_set_lines(buf, index - 1, index, false, centered)
          return true
        end
      end
      return false
    end

    local function render_fact(buf)
      if not fact_result or not vim.api.nvim_buf_is_loaded(buf) then
        return
      end

      local width = vim.o.columns
      for _, win in ipairs(vim.api.nvim_list_wins()) do
        if vim.api.nvim_win_get_buf(win) == buf then
          width = vim.api.nvim_win_get_width(win)
          break
        end
      end

      local title = fact_result.fact and ("Random Fact · " .. (fact_result.metadata.domain or "")) or "Random Fact"
      local body = fact_result.fact or fact_result.error or { "No fact available; check the API key or free-tier quota." }
      if type(body) == "string" then
        body = { body }
      end

      local modifiable = vim.bo[buf].modifiable
      vim.bo[buf].modifiable = true
      replace_marker(buf, FACT_TITLE_MARKER, { title }, width)
      replace_marker(buf, FACT_BODY_MARKER, body, width)
      vim.bo[buf].modified = false
      vim.bo[buf].modifiable = modifiable
    end

    local function on_dashboard_loaded()
      local buffers = dashboard_buffers()
      if fact_result then
        for _, buf in ipairs(buffers) do
          render_fact(buf)
        end
        return
      end
      if request_started or #buffers == 0 then
        return
      end

      request_started = true
      get_random_fact(function(fact, err, metadata)
        fact_result = { fact = fact, error = err, metadata = metadata }
        for _, buf in ipairs(dashboard_buffers()) do
          render_fact(buf)
        end
      end)
    end

    local group = vim.api.nvim_create_augroup("DashboardRandomFact", { clear = true })
    vim.api.nvim_create_autocmd("User", {
      group = group,
      pattern = "DashboardLoaded",
      callback = on_dashboard_loaded,
    })

    require("dashboard").setup(opts)
  end,
}

return {
  dashboard = {
    -- Gemini has free-tier token pricing; actual limits depend on the AI Studio project.
    -- Cerebras is optional and its free access is a time-limited trial.
    provider = "google",
    thinking_level = "low",
    models = {
      google = "gemini-3.8-flash",
      cerebras = "qwen-3.8-27b",
    },
  },
}

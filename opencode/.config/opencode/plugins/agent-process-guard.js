import { execFile } from "node:child_process";
import { homedir } from "node:os";
import { join } from "node:path";
import { Plugin } from "@opencode/plugin";

export default Plugin.define({
  id: "agent-process-guard",
  async setup(ctx) {
    await ctx.tool.hook("execute.before", async (event) => {
      if (event.tool !== "shell") return;
      const command = event.input?.command;
      if (typeof command !== "string" || !/\b(?:pgrep|pkill)\b/.test(command)) return;
      await new Promise((resolve, reject) => {
        const child = execFile(
          "python3", ["-I", join(homedir(), ".local/libexec/agent-process-guard.py")],
          { timeout: 5000, maxBuffer: 65536 },
          (error, stdout, stderr) => {
            if (!error) return resolve();
            reject(new Error(stderr.trim() || "Process-match guard is unavailable; use a native job handle or explicit owned PID."));
          },
        );
        child.stdin.on("error", () => {
          child.kill();
          reject(new Error("Process-match guard input failed; use a native job handle or explicit owned PID."));
        });
        child.stdin.end(JSON.stringify({ tool_input: { command } }));
      });
    });
  },
});

import { afterAll, expect, mock, test } from "bun:test";
import { mkdtempSync, mkdirSync, rmSync, symlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

mock.module("@opencode/plugin", () => ({ Plugin: { define: (plugin) => plugin } }));
const home = mkdtempSync(join(tmpdir(), "process-guard-plugin-"));
let helperHome = home;
mock.module("node:os", () => ({ homedir: () => helperHome }));
const { default: plugin } = await import("../opencode/.config/opencode/plugins/agent-process-guard.js");
mkdirSync(join(home, ".local/libexec"), { recursive: true });
symlinkSync(fileURLToPath(new URL("../shell/.local/libexec/agent-process-guard.py", import.meta.url)),
  join(home, ".local/libexec/agent-process-guard.py"));
afterAll(() => {
  rmSync(home, { recursive: true, force: true });
});

test("OpenCode's native before hook blocks dangerous matching without executing it", async () => {
  let before;
  await plugin.setup({ tool: { hook: async (name, callback) => {
    expect(name).toBe("execute.before");
    before = callback;
  } } });
  await before({ tool: "read", input: { command: "pkill -f worker" } });
  await before({ tool: "shell", input: { command: "git status" } });
  await before({ tool: "shell", input: { command: "pgrep -Af worker" } });
  await before({ tool: "shell", input: { command: "printf '%s' 'pkill -f worker'" } });
  await expect(before({ tool: "shell", input: { command: "pkill -f worker" } }))
    .rejects.toThrow("owned PID");
  helperHome = join(home, "missing");
  try {
    await expect(before({ tool: "shell", input: { command: "pgrep -f worker" } }))
      .rejects.toBeInstanceOf(Error);
  } finally { helperHome = home; }
});

# claude

[← Packages](../README.md#packages) · **Snapshot + live** · [Hooks](#hooks) · [Remote questions](#remote-questions-and-notifications) · [Wake mod](#wake-mod-live)

Claude Code configuration under `~/.claude`. Each part has its own kind:

| Part | Kind | Restore |
| --- | --- | --- |
| `settings.json`, status lines (`statusline-starship.sh` runs `statusline.py`; `subagent_statusline.py` draws the subagent rows) | Snapshot: holds this machine's paths | `install.sh --apply snapshots` copies what is missing on a new machine |
| `CLAUDE.md` (`~/.claude/CLAUDE.md` links here; it imports the shared `~/.config/agents/AGENTS.md`) and the Bridge/Baton skills | Live link | `install.sh --apply links` |
| Hook and plugin entries | Merged into the live `settings.json` | `install.sh --apply hooks` |
| [Wake mod](#wake-mod-live) | Live link; reloads as its files change | `install.sh --apply links` |

## Hooks

`settings.json` defines two `PreToolUse` hooks, the same ones Codex runs (`codex/.codex/hooks.json`):

| Matcher | Command | What it does |
| --- | --- | --- |
| `Bash` | `rtk hook claude` | Runs the command through RTK so its output is filtered before the agent reads it |
| `Bash` | `agent-baton guard` | Denies the agent `agent-baton back` and `cancel`, and, while a `pass` request is out, any shell route to the browser or screen |
| MCP tools whose names contain browser, chrome, computer, playwright, puppeteer, cua or devtools | `agent-baton guard` | Blocks those tools while a `pass` request is out, and never lets them open a password manager |

`install.sh --apply hooks` adds any of these that your live `~/.claude/settings.json` lacks, keeps everything
else in it, and leaves a `settings.json.bak-install` copy. The guard fails closed only while a `pass` request
is out. Claude also loads the `ponytail` plugin (`enabledPlugins` and `extraKnownMarketplaces` in
`settings.json`; see "Plugin: ponytail" in the top-level README), which ships hooks of its own.

## Remote questions and notifications

The settings snapshot enables `remoteControlAtStartup`, `inputNeededNotifEnabled`
and `agentPushNotifEnabled`. Remote Control provides the native phone/browser
answer path; the Claude mobile app must use the same account and allow notifications.
Push delivery also depends on an active Remote Control connection and presence:
Claude suppresses pushes while the connected terminal is focused or being used.
[Remote Control and mobile alerts](https://code.claude.com/docs/en/remote-control#mobile-push-notifications).

`AskUserQuestion` and permission prompts stay pending until answered. The
`dialogExpiry` setting applies to other forwarded dialogs, so changing it does
not implement a question timeout. No automatic-dismissal hook is installed.
[Documented limits](https://code.claude.com/docs/en/remote-control#limitations),
[shared question policy](../agent-baton/README.md#native-questions-and-hooks).

## Wake mod (live)

`.claude/mods/wake` is a Claude Code mod: the animated diorama above the prompt
(the session as a town in the real weather where you are), the crew row
(subagents, Bridge jobs), recaps, the plan in the spinner and the Bridge job tidy scan.
Retired Bridge jobs leave the crew row. The tidy scan counts only retired jobs past their
purge date, excludes dirty worktrees, and asks the root to run `agent-bridge purge`;
it never recommends deleting jobs still within retention. `agent-bridge restore` reactivates
a retained job with its original session.
Unlike the snapshot files, the mod is used in place and reloads as its files change.
It is Claude-only; [Agent Bridge](../agent-bridge/README.md) and
[Agent Baton](../agent-baton/README.md) work in every harness.

### Landscapes and session state

<img src="../docs/images/wake-landscapes.gif" alt="Eight animated Wake landscapes: city at work, harbor awaiting input, beach with workers, mountains with fireworks after passed tests, idle countryside, rainy forest after a failure, desert with a shooting star after a completed job, and sleeping winter tundra." width="100%">

*Actual renderer output, animating. Each scene is an example state, time and weather. `/wake tour` visits them all; `/wake scene <name>` pins one.*

| What changes | What Wake draws |
| --- | --- |
| Turns and tool calls | Structures and coloured windows; the current turn is under construction |
| Bridge workers and Claude subagents | Crew sprites by harness and model tier, plus names, model, effort and age in the crew row |
| Job stops making progress | Amber stale marker |
| Tests pass / command fails / Bridge job finishes | Fireworks / storm / shooting star |
| Plan steps / session mood | Lit lamps / Mochi working, waiting, happy, sad or asleep |
| Place, time and weather | Landscape, sun, moon phase and local weather |

### Crew and quota rows

<img src="../docs/images/wake-dock.gif" alt="Wake's beach scene animating above the activity, crew and quota rows, a prompt and the Claude Code status line. Call-outs name what each sprite is: street lamps are plan steps, a boat is a Codex worker, a bird is a Claude subagent, a constellation is an agy worker, the rising building is the current turn and Mochi shows the session's mood." width="100%">

*Call-outs follow each sprite. Below the scene: activity, crew and quota rows, the prompt, and the Claude Code status line (`statusline.py` here), all demo values.*

The quota row belongs to Wake and appears while Bridge jobs are running. It shows
account numbers, never emails. `h` is five-hour, `w` weekly and `m` monthly
remaining percent; Codex plans report different windows (Plus `h w`, Pro `w`).
agy's `G`, `C`, `A` are Gemini, Claude/GPT and Argon buckets. Codex numbers come
from the local `codex-auth` cache and can be stale; agy numbers come from each
account's cache, refreshed with `agent-bridge quota --backend agy`.

In the capture, Codex 01–02 are Pro and 03–04 are Plus; `*` marks the active
account. A low window colors that account's quota text peach.

### Use and check

Use the live mod in place:

```sh
ln -s ~/dotfiles/claude/.claude/mods ~/.claude/mods
```

`settings.json` loads it in every session through
`"env": { "CLAUDE_CODE_PLUGIN_DIRS": "~/.claude/mods/wake" }`, and an
interactive session reloads it when its files change, so edits here apply live.

- `/wake` summarises; `/wake tour` plays every landscape for 12 s, a whole day in each; `/wake scene <city|harbor|beach|mountains|countryside|forest|desert|tundra|auto>`
  pins a landscape to the current place; `/wake place <city|auto>` overrides the
  IP-based location (GeoJS, then ipwho.is; weather from Open-Meteo; all keyless).
- Pins, the place and cached weather live in the mod's store
  (`~/.claude/plugins/store/wake_*.json`), not here.
- Checks, from the mod folder: `claude plugin validate .`, `claude plugin test .`,
  and `npx -y -p typescript tsc -p .` (the engine writes `.claude-plugin/types/`
  on load; it is ignored).
- `bun dev/showcase.ts` and `bun dev/dock.ts` render the animation frames behind the README GIFs
  ([docs/tools](../docs/tools/README.md) turns them into images).
- Look at a landscape before changing it: `bun dev/preview.ts <landscape>` writes
  a sheet of every day phase, weather, effect and event to `dev/<landscape>.png`.

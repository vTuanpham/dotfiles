# claude

[← Packages](../README.md#packages) · **Snapshot + live** · [Hooks](#hooks) · [Remote questions](#remote-questions-and-notifications) · [Wake mod](#wake-mod-live)

Claude Code configuration under `~/.claude`. Each part has its own kind:

| Part | Kind | Restore |
| --- | --- | --- |
| `settings.json`, status lines (`statusline-starship.sh` runs `statusline.py`; `subagent_statusline.py` draws the subagent rows) | Snapshot: holds this machine's paths | `install.sh --apply snapshots` copies what is missing on a new machine |
| `CLAUDE.md` (`~/.claude/CLAUDE.md` links here; it imports the shared `~/.config/agents/AGENTS.md`), Bridge/Baton and the [pstack skills](../agents/README.md#engineering-skills) | Live link | `install.sh --apply links` |
| Hook and plugin entries | Merged into the live `settings.json` | `install.sh --apply hooks` |
| [Root stop safety net](.claude/hooks/README.md) | Script is a live link; entries merge into settings | `install.sh --apply links`, then `install.sh --apply hooks` |
| [Wake mod](#wake-mod-live) | Live link; reloads as its files change | `install.sh --apply links` |

## Cache and thread reuse

Within included subscription usage, Claude Code's main conversation defaults to
a one-hour prompt cache; subagents and most other requests default to five
minutes. Usage credits, API keys and cloud-provider requests default to five
minutes for both. Explicit settings can change these defaults; see the
[official prompt-cache guide](https://code.claude.com/docs/en/prompt-caching#which-ttl-each-request-gets).
Reuse context when relevant, and start fresh when unrelated history outweighs
the benefit; a warm cache does not make an oversized conversation free.

## Hooks

The settings snapshot selects `/bin/bash` for Claude's Bash tool through
[`CLAUDE_CODE_SHELL`](https://code.claude.com/docs/en/env-vars). Interactive Zsh
keeps its native parsing; agent compatibility does not change `.zshenv` options.

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

The [root Stop hook](.claude/hooks/README.md) reminds the root once to arm a
Bridge watch or acknowledge unread work before ending a turn. It allows user
questions and fails open on errors. Disable with `AGENT_BRIDGE_STOP_GUARD=0 claude`.

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
| Bridge workers and Claude subagents | Crew sprites by harness and model class, plus compact crew rows |
| Job stops making progress | Amber stale marker |
| Tests pass / command fails / Bridge job finishes | Fireworks / storm / shooting star |
| Plan steps / session mood | Lit lamps / Mochi working, waiting, happy, sad or asleep |
| Place, time and weather | Landscape, sun, moon phase and local weather |

### Crew and quota rows

Bridge crew has one line per job: title, harness and model class, state, effort,
time since the last event, memory against its cap, and peer links from the last
15 minutes. Dead quota accounts fold into one range. Color distinguishes
families and states; short marks replace repeated model and status words. All
rows use the same columns, so each worker keeps its own harness and class. Narrow
layouts shrink titles and omit the same lower-priority columns for every row;
`/wake legend` explains the marks. A stalled or blocked job carries its reason
when there is room. Finished jobs remain until Bridge's `result` or `ack`.

The compact list follows Claude Code's subagent presentation: one recognizable
marker and name, a brief state and small counters, with color providing emphasis
and longer explanations kept out of the list. The row uses vendor logos where the
terminal supports inline images, with text alternatives otherwise. Model-maker
logos appear in hover details only when the model ID identifies the maker.
The [Claude Code documentation](https://code.claude.com/docs/en/sub-agents)
describes its subagent workflow and status access.

Classes are 1 Haiku/Luna, 2 Sonnet/Terra, 3 Opus/Sol and 4 Fable/Astra;
unrecognized models fall back to class 2. Each harness has four scene sprites.
A filling circle beside the harness mark (◔ ◑ ◕ ◉) shows the class, and a
five-step signal meter shows effort, lit steps against dots.
If the crew will not fit alongside the scene, Wake temporarily gives the rows
the available space instead; an overflow count indicates any remaining rows.
A stall mark comes from Bridge's shared
[stall classifier](../agent-bridge/src/agent_bridge/guide/status.md#bounded-waits-and-one-stall-classifier-v12);
known waits have their own reasons. Finished jobs stay as `done` until Bridge's
`result` or explicit `ack` acknowledges their completion.

Bridge jobs, quota numbers and tidy eligibility come from
[`agent-bridge status --json`](../agent-bridge/src/agent_bridge/guide/status.md).
Wake maps the shared state and stall reason; heavy waits, root pauses and retry
backoff stay normal known states. Colored gutter lanes join connected peers;
← points to the recipient, ─, ━ and ═ represent 1, 2–4 and 5+ messages,
and ┄/┆ show a declared peer or dependency wait. Message links dim after five
minutes and disappear after 15. The gutter shrinks with the terminal; where a
group cannot fit, the existing ↗/↙ peer marks remain. Root messages have their
own ↗r (worker → root) and ↙r (root → worker) gutter marks. Clear scene paths
connect workers to Mochi. Hover details show the scrubbed preview and distinguish
Bridge observing worker output from sending a root prompt or steer; neither
proves the recipient read it. The root endpoint is the owner namespace across
session handoffs. The native Claude `statusline.py` still renders
Claude's own session/context/cost input; it has no separate Bridge parser.

The quota rows belong to Wake and appear while Bridge jobs are running. They show
account numbers, never emails, with bars for remaining quota. `h` is five-hour,
`w` weekly and `m` monthly; Codex plans report different windows (Plus `h w`, Pro `w`).
agy's `G`, `C`, `A` are Gemini, Claude/GPT and Argon buckets. Codex numbers come
from the local `codex-auth` cache and can be stale; agy numbers come from each
account's cache, refreshed with `agent-bridge quota --backend agy`.

`*` marks the active account; `?` means its quota is unknown, and `~` marks a
stale reading or one without a known sample time.

### Use and check

Use the live mod in place:

```sh
ln -s ~/dotfiles/claude/.claude/mods ~/.claude/mods
```

`settings.json` loads it in every session through
`"env": { "CLAUDE_CODE_PLUGIN_DIRS": "~/.claude/mods/wake" }`, and an
interactive session reloads it when its files change, so edits here apply live.

- `/wake` summarises; `/wake legend` explains the crew; `/wake tour` plays every landscape for 12 s, a whole day in each; `/wake scene <city|harbor|beach|mountains|countryside|forest|desert|tundra|auto>`
  pins a landscape to the current place; `/wake place <city|auto>` overrides the
  IP-based location (GeoJS, then ipwho.is; weather from Open-Meteo; all keyless).
- Pins, the place and cached weather live in the mod's store
  (`~/.claude/plugins/store/wake_*.json`), not here.
- Checks, from the mod folder: `claude plugin validate .`, `claude plugin test .`,
  and `npx -y -p typescript tsc -p .` (the engine writes `.claude-plugin/types/`
  on load; it is ignored).
  If every test file reports "did not load" with child exit code 0, check sandbox
  restrictions on the child harness; rerun the same command outside the sandbox
  when authorized. Type checking does not replace the runtime suite.
- `bun dev/showcase.ts` and `bun dev/dock.ts` render the animation frames behind the README GIFs
  ([docs/tools](../docs/tools/README.md) turns them into images).
- `bun dev/crew.ts <codex|agy|claude|opencode>` renders the four sprite classes;
  `bun dev/crew-review.ts` renders synthetic before/after rows at three widths.
- Look at a landscape before changing it: `bun dev/preview.ts <landscape>` writes
  a sheet of every day phase, weather, effect and event to `dev/<landscape>.png`.
- Paint scene cards in the same Raster as the animation. The Client captures pointers
  only: independently redrawing an overlapping Client can briefly clear the fullscreen
  scene. Check continuous mouse movement in the configured terminal mode; hook traces
  and the test kit do not verify terminal compositing.

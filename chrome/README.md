# chrome

[← Packages](../README.md#packages) · **Live adapter** · **Manual extension registration**

| Layer | Owner | Setup |
| --- | --- | --- |
| Extension download | Chrome Web Store | System registration below; Chrome downloads it on normal startup |
| ChatGPT native host + browser runtime | Windows ChatGPT app | Settings → Computer Use → Chrome |
| WSL stdio transport | [`chatgpt-browser`](.local/bin/chatgpt-browser) | `./install.sh --apply links` |
| Browser operation rules | App's unchanged bundled Chrome skill | Link its folder into local Codex skills |

## Extensions for Linux Chrome

Chrome extensions for every profile. Google Chrome on Linux installs an extension for all profiles and all users when a
`<extension-id>.json` with the Web Store update URL sits in a system extensions dir.
A per-user `External Extensions` folder is not honored on Linux (tested on the Dev channel).
Users can still disable or remove these; Chrome does not reinstall a removed one.

| File | Extension |
| --- | --- |
| `fcoeoabgfenejglbffodgkkbkcdhcgfn.json` | Claude in Chrome (Anthropic) |
| `hehggadaopoacecdllhhajmbjkdcmajg.json` | ChatGPT (OpenAI) |

Install (needs sudo; both documented system paths, so any channel finds them):

```sh
sudo install -d -m 755 /usr/share/google-chrome/extensions /opt/google/chrome/extensions
sudo install -m 644 -t /usr/share/google-chrome/extensions ~/dotfiles/chrome/extensions/*.json
sudo install -m 644 -t /opt/google/chrome/extensions ~/dotfiles/chrome/extensions/*.json
```

Start or restart **normal Chrome in the profile you use** afterwards. The JSONs
register downloads; they are not copies of the installed extensions. A headless
test browser with `--disable-extensions` does not install or activate them.
Verify both extension cards and their enabled switches at `chrome://extensions/`.
Authentication and account consent remain per profile.

Claude Code's Chrome integration is [documented as unsupported in WSL](https://code.claude.com/docs/en/chrome).
The Claude extension can still install and sign in; that alone does not establish
a Claude Code connection. Check `/chrome` in Claude Code before relying on it.

## ChatGPT from WSL: gap and local compatibility patch

Start diagnosis with `chatgpt-browser doctor` (read-only). It checks Windows
native-host/runtime files, Codex's MCP launcher, and configured Linux profiles.
Use `doctor <user-data-dir>` to require a particular Linux registration; unused
profiles are informational. The script uses UV to select Python with TOML support,
so it does not depend on the system Python version.

Local checks do not prove a live extension connection. Finish with browser
discovery through the harness's native Chrome tools; no separate browser client
or alternative control route is needed.

**The desktop app's WSL browser integration is the product gap.** The inspected
Windows app reports browser availability as `reason=wsl-disabled` when running
the agent in WSL. This is an installed-build observation, not a published promise
of support. Its Chrome side chat uses a separate availability path.

**Missing native-host registration is a local installation fault.** The extension
reported `Specified native messaging host not found`; Chrome requires a separate
host manifest and, on Windows, a registry entry. Repair that through the app's
Computer Use setup first. The local repair used the app's unchanged bundled host
and installer. No extension source or signed app archive was patched.

The adapter connects WSL Codex to that existing Windows runtime. It discovers
the registered host, reads the app-managed runtime paths, and forwards browser
stdio. Linux Chrome can use the same host through its own native-host manifest.
It needs no Chrome remote-debugging setting or DevTools server.

**Transport is not native WSL integration.** The Windows runtime rejects native
WSL sandbox metadata (`sandboxCwd` is a Linux file URI). An explicitly authorized
`chatgpt-browser mcp --disable-sandbox` uses the runtime's documented exception
for its Windows JavaScript kernel. Keep it scoped to this browser launcher;
Codex's own sandbox and mandatory approval review remain enabled. A standalone
client without an attached execution reviewer fails strict approval checks.
Neither launching Chrome nor opening a URL proves extension control works.

| Route | Transport |
| --- | --- |
| WSL Codex → Windows runtime | `chatgpt-browser mcp --disable-sandbox` after explicit authorization |
| Windows Chrome → runtime | App-installed native host |
| Linux Chrome → runtime | `chatgpt-browser` native-messaging adapter |

Requirements: WSL interoperability, Python 3.11+, `wslpath`, Windows PowerShell,
and the Windows ChatGPT app with its Chrome plugin and native host installed.
Account/workspace access and site permissions still apply. This is a local
compatibility path, not official WSL desktop integration or a policy override.

1. Link the adapter: `./install.sh --apply links`.
2. Configure `node_repl` in local WSL `~/.codex/config.toml` with an **absolute
   Python 3.11+ interpreter** as `command` and the absolute adapter path followed
   by `mcp` as `args`. WSL-to-Windows use also needs `--disable-sandbox` in those
   args after explicit authorization. The default keeps the kernel sandbox;
   the adapter never silently enables this exception. Keep machine paths and
   authorization outside this public repository. Reload MCP configuration or
   start a fresh chat to expose its `js` tool.

3. For Linux Chrome, register its existing **user-data root**, not `Default` or
   `Profile 1` beneath it. For example, on the Dev channel:

   ```sh
   chatgpt-browser register-linux ~/.config/google-chrome-unstable
   ```

   Use `~/.config/google-chrome` for Stable, or the actual custom root. The command
   preserves a different existing host and keeps the app's allowed extension
   origins. The generated manifest stays outside Git.
4. `chatgpt-browser paths` reports the official skill and browser-client URL.
   Link that skill's folder to `~/.codex/skills/control-chrome` locally. Browser
   actions use the official `js` tool and unchanged skill. During bootstrap,
   import the returned `client_url`: this runtime uses Windows paths, not WSL
   `/mnt/...` paths.

The adapter checks the app and host runtime paths agree and refuses extra runtime
flags from app configuration. App upgrades can require repeating browser setup.
Only the explicit launcher option disables the kernel sandbox; it does not
change approval policies or bring over the computer-control service.
Check the selected browser instance when both Windows and Linux Chrome are open.

## Visible agent tabs

For connected extension sessions, keep the task's controlled tabs in a named
group such as **🤖 Agent · Google Photos**, using a consistent warm color. Reuse
the task's existing group instead of making duplicates. On handoff, label it
**Review · Google Photos**. Keep unrelated tabs outside it, and use only group
controls documented by the selected browser runtime. A normal URL launch does
not provide group management or indicate an active automation connection.

To remove the compatibility path, remove the local `node_repl` MCP entry and only
the Linux native-host manifest generated above. The app owns the Windows host;
manage that through its UI. Extension registration and extension account login
are separate from the adapter.

Sources: [OpenAI browser extension setup](https://learn.chatgpt.com/docs/chrome-extension),
[Codex MCP configuration](https://learn.chatgpt.com/docs/extend/mcp?surface=cli),
[Chrome external extension registration](https://developer.chrome.com/docs/extensions/how-to/distribute/install-extensions),
[Chrome native messaging](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging).

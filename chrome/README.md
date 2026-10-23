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

| Route | Transport |
| --- | --- |
| WSL Codex → Windows runtime | `chatgpt-browser mcp` |
| Windows Chrome → runtime | App-installed native host |
| Linux Chrome → runtime | `chatgpt-browser` native-messaging adapter |

Requirements: WSL interoperability, Python 3.11+, `wslpath`, Windows PowerShell,
and the Windows ChatGPT app with its Chrome plugin and native host installed.
Account/workspace access and site permissions still apply. This is a local
compatibility path, not official WSL desktop integration or a policy override.

1. Link the adapter: `./install.sh --apply links`.
2. Add this **locally** to WSL `~/.codex/config.toml`:

   ```toml
   [mcp_servers.node_repl]
   command = "/usr/bin/env"
   args = ["chatgpt-browser", "mcp"]
   startup_timeout_sec = 20
   tool_timeout_sec = 180
   ```

3. For Linux Chrome, register its existing **user-data root**, not `Default` or
   `Profile 1` beneath it. For example, on the Dev channel:

   ```sh
   chatgpt-browser register-linux ~/.config/google-chrome-unstable
   ```

   Use `~/.config/google-chrome` for Stable, or the actual custom root. The command
   preserves a different existing host and keeps the app's allowed extension
   origins. The generated manifest stays outside Git.
4. `chatgpt-browser paths` reports the official skill and browser-client URL.
   Link that skill's folder to `~/.codex/skills/control-chrome` locally. Start a
   fresh Codex session to load it and the MCP server. Browser actions use the
   official `js` tool and unchanged skill. During bootstrap, import the returned
   `client_url`: this runtime uses Windows paths, not WSL `/mnt/...` paths.

The adapter checks the app and host runtime paths agree and refuses extra runtime
flags. App upgrades can require repeating the app's browser setup. It preserves
the runtime's normal sandbox and does not bring over the computer-control service.
Check the selected browser instance when both Windows and Linux Chrome are open.

To remove the compatibility path, remove the local `node_repl` MCP entry and only
the Linux native-host manifest generated above. The app owns the Windows host;
manage that through its UI. Extension registration and extension account login
are separate from the adapter.

Sources: [OpenAI browser extension setup](https://learn.chatgpt.com/docs/chrome-extension),
[Codex MCP configuration](https://learn.chatgpt.com/docs/extend/mcp?surface=cli),
[Chrome external extension registration](https://developer.chrome.com/docs/extensions/how-to/distribute/install-extensions),
[Chrome native messaging](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging).

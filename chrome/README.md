# chrome

[← Packages](../README.md#packages) · **Manual** · not installed by `install.sh`; needs `sudo`

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

Restart Chrome afterwards. Claude Code's Chrome integration is documented as unsupported in
WSL, so check `/chrome` in Claude Code before relying on it.

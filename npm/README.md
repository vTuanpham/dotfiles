# npm

[← Packages](../README.md#packages) · **Snapshot** · `./install.sh --apply snapshots`

`~/.npmrc`: one line, `prefix=`, pointing npm's global prefix at an NVM-managed Node
directory so global installs land beside that Node. The path carries this machine's NVM version; edit it to
the one you use. See [Node and NVM](../shell/README.md#node-and-nvm) for how the shell preserves
`~/.local/bin/{node,npm,npx}` and handles the global prefix.

Global packages the other tools expect (Claude Code, Codex, `codex-auth`) are installed by `install.sh`.

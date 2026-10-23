# github

[← Packages](../README.md#packages) · **Live** · `install.sh --apply links` links the credential adapter

`github-mcp` starts GitHub's official native MCP server using the credential
already managed by `gh`. No token is copied into dotfiles, tool arguments or
shell startup. Authentication errors never echo credential output.

Install `gh` and the official `github-mcp-server` binary for your platform,
checking the release checksum. `install.sh --apply apt` supplies `gh` when its
command is missing. Authenticate with `gh auth login --hostname github.com`.
Both binaries, credential stores and machine-local MCP settings stay outside Git.
Without an OS keyring, `gh` falls back to a plaintext credential file. Keep its
directory owner-only and the file mode `0600`; never copy it into this repository.

```sh
codex mcp add github -- github-mcp --toolsets repos,issues,pull_requests,actions --read-only
```

This exposes repository, issue, pull-request and CI reads. Use `gh` for authorized
writes. Disable the unauthenticated GitHub plugin server in local configuration
when using this registration, so there is one owner for GitHub tools.
Other MCP hosts can launch the same stdio command. Reload after registration and
verify discovery plus one bounded public repository read.
`Auth: Unsupported` in `codex mcp list` refers to harness-managed OAuth;
this stdio adapter authenticates through `gh` instead.

| Work | Existing command |
| --- | --- |
| PR state | `rtk gh pr view --json number,title,state,statusCheckRollup` |
| Failed CI | `rtk gh run view RUN_ID --log-failed` |
| Local changes | `rtk git status` and `rtk git diff` |
| Rendered README | Native Chrome tools, after content/CI checks |

The adapter requires `gh` authentication instead of opening an unexpected OAuth
flow at harness startup. Revocation or removing the server registration stops
access; credential rotation remains `gh`'s job.

Sources: [GitHub MCP setup](https://github.com/github/github-mcp-server/blob/main/docs/installation-guides/install-codex.md),
[server configuration](https://github.com/github/github-mcp-server#configuration),
[CLI authentication](https://cli.github.com/manual/gh_auth_login).

---
name: agent-baton
description: Hand login, 2FA, sudo/ssh/gpg and other secret prompts to the human without seeing them, or collect ordinary answers and choices after a native harness question goes unanswered. Question reminders belong to the root/coordinator only. Never ask for secrets in chat or type them yourself.
---

# agent-baton

A cross-harness CLI for human handoffs through Windows notifications or a phone over ntfy and Tailscale. Secret forms hold answers privately and type them into an approved app. Ordinary question forms return readable answers to the agent. These are separate modes: never collect credentials through `question`.

Requests belong to one conversation, which Codex and Claude Code supply automatically; on other harnesses the CLI's error says how to set `AGENT_BATON_SESSION`. Keep the returned request id for `wait`/`withdraw`/`type`/`forget`; never pick up another session's pending question.

For several ordinary questions or a disposable UI, `form <json-file>` composes built-in text, choice and select-many controls. `wait` returns answers keyed by question id; optional unanswered fields are omitted. This follows the same root-only reminder policy. The CLI help owns the JSON schema; do not invent an HTTP endpoint or supply HTML/scripts.

## When to reach for it
- An ordinary harness question remains unanswered: the root/coordinator can use `question` with the same wording, choices and single/multiple selection mode, following the shared reminder policy. Free text and yes/no questions work too. Use the harness's native question tool first, preferring its nonblocking variant (chat if unavailable); workers report questions to the root. `wait <id>` returns the answer as JSON. `withdraw <id>` closes an obsolete reminder if the human answers in chat first; cancellation or expiry is never consent. Harness permission dialogs still apply.
- A page or app asks for an email, password, 2FA or one-time code, or an API key: `ask` the human, then `type` the answer into the field.
- A command asks for a password (`sudo`, ssh passphrase, gpg, git credentials): `run -- <command>`. The human approves the exact command and types the password on a page.
- Only a human can do the step (CAPTCHA, passkey, QR, device prompt): `pass`, which blocks your browser and screen tools until they hand it back.

A blocked agent cannot run the reminder timer. Use the harness's supported remote-answer/notification path in that case; never fake a reply or simulate keys to dismiss the prompt. [Native question support](../../../../agent-baton/README.md#native-questions-and-hooks) documents the supported paths and limits.

## Secret handoffs
1. `ask` builds the form and returns an id at once; the human may be on their phone, so run `agent-baton wait <id> --until-done` in the background and do other work meanwhile.
2. Run `agent-baton focus --id <id>`, then click the field with your own tools before `agent-baton type <name> --id <id>`. Extension clicks can run in background tabs; ensure the intended tab is selected for this desktop typing step. Windows typing refuses a background window instead of changing focus and losing the field.
3. Window titles change between steps (Google: "Sign in", then "Welcome"), and the human approves only the titles you list, so pass `--window` for every title you expect.
4. Verify that the masked field filled and that submission succeeded before `forget <id>` clears the answer. Never read its value back. Answers expire after about ten minutes. If a baton is cancelled or expires, stop and ask the user; do not retry on your own.

The CLI documents itself. Run `agent-baton --help` for the exact commands, flags and rules before first use; read it when you need it, not earlier. Never put a secret in chat, a file or a command line.

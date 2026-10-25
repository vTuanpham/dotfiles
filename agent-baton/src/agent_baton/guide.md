agent-baton hands a question or secret prompt to the human on their phone or PC.
Ordinary answers are returned to the agent; secrets stay private and are typed into an approved app.
Never put secrets in a question or chat.

Native tools: `agent-baton mcp` serves MCP over stdio. Register with
`codex mcp add agent_baton -- agent-baton mcp`, then reload the harness.
Every call supplies its conversation owner, matching the CLI's session namespace;
the package README lists tools and isolation. Secret values are never inputs or
results. CLI commands below remain available for every workflow.

Pick the command
  question  ordinary text or multiple-choice question; wait returns the answer as JSON.
  form   one-off ordinary form from a JSON file; wait returns answers keyed by question id.
  ask    any login or secret you must enter in a browser or app (the usual case).
  env    have the human store a secret in one or more environment files.
  run    a command that needs a password: sudo, ssh passphrase, gpg, git credential prompt.
  pass   only when the human must do the sign-in themselves on the PC (CAPTCHA, passkey, QR).
         Browser and screen tools are blocked until they hand it back.

Session isolation
  Codex (CODEX_THREAD_ID) and Claude Code (CLAUDE_CODE_SESSION_ID) are identified automatically. Other
  harnesses must supply AGENT_BATON_SESSION with a unique, nonsecret conversation id on every call
  (create one once, then reuse it in this conversation); an explicit value overrides the automatic one.
  Example: AGENT_BATON_SESSION=conversation-UUID agent-baton question "Which scope?"
  Use the same value for wait, withdraw, type, forget and status. Never set a shared value in shell startup.
  AGENT_BATON_BY changes the display name only; it does not isolate sessions.
  Default selection and explicit ids/sites are limited to your session. Without an owner, state commands
  fail closed; old requests without an owner are never adopted. Human pages remain tied to their request.
  Two simultaneous questions have separate notification tags and one-use reply links. Answering one
  does not answer, consume or withdraw the other. Multiple open requests in one session require an id.
  The shared browser/screen lock during a human login is global for privacy; questions never take it.

Ordinary questions (root/coordinator only)
  Use your harness's native question tool first, preferring its nonblocking variant (chat if unavailable).
  If the root is able to keep working and the question is still
  pending after the delay in your shared instructions, send one reminder with the same wording/options:
  agent-baton question "Which scope?" --option "Current project" --option "All projects"
  Omit --option for free text. Choices always include Other with a text box; none is selected for them.
  Yes/no or approval questions use explicit --option "Yes, proceed" --option "No" choices.
  Add --multiple for select-all-that-apply; answer is always a JSON list in option order, with Other last.
  Without --multiple, answer is one string. Each invocation collects one question.
  agent-baton wait <id> --until-done      (as a background command: it ends when the human answers or it expires)
  An answered question returns JSON with id, question and answer. A foreground call needs
  --timeout N instead; exit 75 then means still held.
  No browser tools are blocked and no typing happens. Answers are readable by the agent and stored
  locally (0600); resolved state is cleaned on a later launch after about a day. Never use this for secrets.
  If the human answers in the harness first: agent-baton withdraw <id>
  Withdrawal only closes an ordinary question and never approves anything. Workers send questions
  to their root instead of notifying the human. Silence, expiry and cancellation are not consent.
  A question form does not replace mandatory harness permission/approval dialogs.
  This CLI does not monitor harness questions or start a reminder timer; the active root does that.
  For blocking native questions, prefer the harness's supported remote-answer/notification path.
  Do not simulate keys or fabricate answers to dismiss the prompt. Native hooks have no portable
  cancel-after-delay operation; see the README's Native questions and hooks section.

One-off forms (the same root-only reminder policy applies)
  agent-baton form /tmp/decision.json
  JSON shape:
    {"title":"Review choices","questions":[
      {"id":"scope","question":"Scope?","type":"choice","options":["Local","Shared"]},
      {"id":"platforms","question":"Platforms?","type":"multiple","options":["Linux","Windows"]},
      {"id":"notes","question":"Other constraints?","type":"text","required":false}
    ]}
  Types: text (multiline), choice, multiple. required defaults to true; unanswered optional fields
  are omitted from the returned answers object. --ttl controls expiry; withdraw also works on forms.
  wait returns {"id":"...","title":"...","answers":{"scope":"Local","platforms":["Linux"]}}.
  Bounds: definition 64 KiB; title 120 characters; optional top-level reason 300; 1–10 questions;
  unique lowercase ids up to 32 characters; question 2000; at most 10 options of 300 each; answer 2000.
  Unknown keys, duplicate JSON keys, non-finite values, invalid types and ambiguous submissions fail.
  This is a CLI JSON interface, not a public HTTP API. Forms use built-in controls, never arbitrary
  agent-supplied HTML or scripts. Do not use this interface for credentials.

Logins with ask + type
  1. Look at the page with your own tools to see what it wants (email, password, code).
  2. `agent-baton windows` lists window titles. Pick a distinctive part of the title of the
     window the field is in, e.g. "Sign in" or "Google Accounts". It may not be a terminal.
     Titles often change between steps (Google: "Sign in", then "Welcome"): repeat --window
     for each title you expect, because the human approves exactly those.
  3. agent-baton ask --window "<title part>" --reason "<why>" email="Account email" password:secret=Password
     Each field is name[:secret]=Label. `:secret` shows as a password input. The human sees the
     fields, your reason and the window title, then answers on a form.
  4. `agent-baton wait <id> --until-done` in the background, and do other work meanwhile.
  5. `agent-baton focus --id <id>` activates the approved window. Then click its field with your own tool
     and `agent-baton type <name> --id <id>` (`--clear` replaces existing text). Extension browser actions
     can work in background tabs; select the intended tab for this desktop typing step. Windows typing
     refuses a background window instead of stealing field focus. Check that the masked field filled
     before submitting (`--enter` submits immediately). Never read a password value back.
  6. `agent-baton forget <id>` after confirming submission succeeded. Answers also expire on their own
     (default 10 minutes).

Store a human-supplied environment secret
  agent-baton env LIQUID_API_KEY --prefix liquid_ --file ~/.config/shell/secrets.local.sh --file .env --reason "Configure the API client"
  The human gets a masked field with the variable name, target files and reason. The value is stored
  by the daemon and never returned to the agent. Existing entries are replaced; `.sh` files get
  `export`, other files get plain `NAME=value`. Existing targets are backed up under
  `$XDG_STATE_HOME/backups/env-secrets/` (or `~/.local/state/backups/env-secrets/`); the backup's
  `origin.json` records restore paths. Targets and backups are mode 0600; symlinks and group/world
  writable targets are refused. Prefix and value must contain only letters, numbers, `_`, `.`, `-`.
  `wait <id>` reports the paths and backup location, never the value. Cancellation or expiry writes nothing.

Commands that need a password
  agent-baton run --reason "<why>" -- sudo apt-get install -y foo
  The human reviews the exact command, presses Run and types any password on the page. Then
  `agent-baton wait <id>` returns the exit code, stdout and stderr (the prompt text stays private).

Rules
  - Never put a secret in agent-visible chat or a command line. Use `env` only when the human asked to store it in environment files.
  - `back` and `cancel` belong to the human; the guard denies them to you. Agents may withdraw only ordinary questions.
  - cancelled or expired means stop and ask the user; do not retry on your own.
  - While a `pass` baton is out, browser, screen and cua-driver tools are denied. That is expected.
  - Password managers, saved passwords and chrome://settings/passwords are never to be browsed.
  - If no channel reached the human, tell them in chat. `agent-baton doctor` names what is broken.

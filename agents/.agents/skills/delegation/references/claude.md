# Native Claude workers

Use the native Agent tool and its current schema. Native calls accept model
aliases; custom agent definitions can select a full model ID. Check available
aliases and effective model rather than assuming a family alias pins a version.
Choose effort only where the installed tool supports it; environment/settings
can override requested settings. A fork can have different inheritance rules.

Background workers have a narrower built-in tool set than foreground workers.
In particular, do not brief a background worker to ask the user directly or
assume it can use every root tool. Questions return to the root.

Use native messaging/resume for related work and native completion notifications
instead of shell polling. Keep the local Claude preferences for root and worker
selection; this reference describes mechanics, not permission to override them.

Source: [Claude subagents](https://code.claude.com/docs/en/sub-agents).

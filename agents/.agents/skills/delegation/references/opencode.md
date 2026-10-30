# Native OpenCode workers

Use the current Task/subagent capability, not a Bridge-launched OpenCode process.
Discover available agents and providers from the native session. OpenCode model
IDs are provider-qualified; OpenCode is a harness, not one fixed model family.

Native subagents inherit the invoking agent's model when their definition has no
model override. Choose an existing appropriate agent or a supported custom agent
definition when a different model/tool policy is needed; do not invent per-call
model fields that the current tool does not expose.

Check task permissions, model variants, writable ownership and whether the native
call blocks or reports completion asynchronously. Resume a related task through
its returned identity where supported. Keep provider retention policy separate
from price; a free endpoint does not establish zero retention.

Source: [OpenCode agents](https://opencode.ai/docs/agents/).

---
description: Bootstrap, once — generate Claude Code settings from policy, and report what does not map.
scripts:
  py: scripts/claude_config.py
---

# GitHub Lifecycle Claude Config

Two steps, because this writes the file that decides what an agent may do.

```bash
{SCRIPT} \
  propose --out .specify/lifecycle/claude-settings-<run-id>.json
```

```bash
{SCRIPT} \
  apply --proposal .specify/lifecycle/claude-settings-<run-id>.json \
  --out .claude/settings.json
```

Apply refuses anything that is not a proposal this command produced — including
a proposal from the OpenCode generator, which would otherwise write the wrong
schema into the wrong agent's file.

## Three kinds of unmapped, and they are not the same

**Not applicable.** Session sharing and provider selection are capabilities
Claude Code does not have. Reporting them as gaps spends the reader's attention
on something that is not there. Say "does not apply", not "not enforced".

**A genuine gap.** Cost and runtime ceilings have no setting and nothing
compensating. Report it plainly.

**Enforced better here than elsewhere.** `plugin_default: deny` and
`mcp_default: deny` have no primitive in OpenCode and were reported as gaps
there. Here they map: `enableAllProjectMcpServers: false` and an
`enabledPlugins` allowlist. Do not carry the other integration's gap list
across — it understates what this agent enforces.

## The default mode is the shell

Allowing `Bash(.specify/lifecycle/verify)` is not opening the shell;
`defaultMode` still asks. `bypassPermissions` and `acceptEdits` both open it, and neither is
a way to get a blocked command through.

## Never

- Apply a proposal nobody approved.
- Report a not-applicable rule and a real gap in the same breath.
- Add a rule to `allow` because a run was interrupted by a prompt. The prompt
  is the policy working.

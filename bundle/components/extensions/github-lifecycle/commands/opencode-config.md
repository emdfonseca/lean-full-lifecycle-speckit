---
description: Bootstrap, once — generate the OpenCode configuration from policy, and report what it cannot enforce.
scripts:
  py: scripts/opencode_config.py
---

# GitHub Lifecycle OpenCode Config

Two steps, because this writes the file that decides what an agent may do.

```bash
{SCRIPT} \
  propose --out .specify/lifecycle/opencode-config-<run-id>.json
```

Propose writes a proposal and changes no configuration. Show it at a gate.

```bash
{SCRIPT} \
  apply --proposal .specify/lifecycle/opencode-config-<run-id>.json \
  --out opencode.json
```

Apply refuses anything that is not a proposal this command produced.

## Report both halves

**What was configured.** Shell, web, and external-directory defaults become
permission keys; sharing is disabled; the reviewer's edit permission is denied;
the two verification commands are allowed by pattern while the bash default
stays `ask`.

**What could not be.** `plugin_default: deny` and `mcp_default: deny` have no
permission primitive in OpenCode — only allowlists — so the config cannot
express them. Provider restriction and cost ceilings are likewise absent. Each
is reported with why and what compensates.

One of them, cost and runtime limits, says its compensation is nothing. Report
that plainly. A made-up mitigation is worse than an admitted gap, and this is
the line a reader needs to see.

`fully_enforced: false` is the normal result. Do not describe a generated config
as enforcing the policy.

## Bash patterns are weaker than permissions

Protected pushes, production deploys, and destructive operations are expressible
only as command patterns. A pattern matches commands, not intents, and the
report names the patterns used so somebody can judge whether they are enough.
Adding a pattern is a policy edit, not a fix applied here.

## Never

- Apply a proposal nobody approved.
- Widen the bash default to `allow` because a needed command was refused. Add
  the command, or decide it is not needed.
- Omit the unenforceable list from your report because everything else passed.

---
description: Verify every role's model against the installed OpenCode inventory.
scripts:
  py: scripts/opencode_models.py
---

# GitHub Lifecycle Models

```bash
{SCRIPT} --format json
```

`model-routing.yml` names seven roles. This checks that every model those roles
name is real and permitted, and it writes nothing.

## The inventory is asked for, not remembered

`opencode models` lists what the installed CLI can actually reach. A model list
kept in this repository would be a second copy that drifts, and the copy that
drifts is the one nobody is testing. If the command cannot be run, or reports
nothing, this refuses — an empty inventory verifies every id while appearing to
verify them.

## Unresolved is not a failure to fix by choosing

A role with a null primary is reported `unresolved` and the run is still clean.
That null is a decision deferred until there is evidence, not an oversight.
Report the unresolved roles; do not pick a model to make the output green.
`fully_resolved` in the JSON says whether anything is actually mapped.

## Fallbacks

A fallback is checked exactly like a primary. It runs when the primary is
unavailable, which is precisely when nobody is in a position to discover it was
never real.

## Recording a resolution

Once a mapping verifies, record it with the date it was evaluated and the date
it expires:

```bash
{SCRIPT} \
  --format json
```

Recording refuses three things: a mapping that failed verification, one where
nothing was verified, and one with no expiry. The third matters most. A
resolution with no visible expiry is trusted indefinitely, which is how a model
that was withdrawn stays in a config.

How long a resolution stays current is a decision somebody makes. The recorder
will not invent an interval.

An expired record is reported expired and is not the mapping in force. Say that
plainly rather than reporting the roles it contains as if they were current.

## Roles nothing asks for

A role in the policy that no consumer names is reported unused. Report it; do
not delete it. Removing somebody's role because nothing references it yet is a
decision, not tidying.

## Never

- Add a model id to the policy without running this.
- Widen `approved_providers` to get a mapping through. That is a decision about
  which vendors this project trusts, not a step in resolving a model.
- Report `unresolved` as `verified`.

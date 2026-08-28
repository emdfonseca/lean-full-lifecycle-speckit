---
description: Yours to run — report one item's state, blockers, children and next step. Writes nothing.
scripts:
  py: scripts/router.py
---

# Work Status

What is true about **one item**, and what happens to it next.

This is not `speckit.github-lifecycle.status`. That one reports the board: the
whole queue, every audit finding, the working tree. This one reports the item
you are working on. Run that one to choose what to pick up; run this one once
you have picked it up.

## Gather, then route

The router reads policy and never the board, so supply the board facts:

1. Resolve the item. An explicit `#n` wins. Otherwise read
   `SPECIFY_FEATURE_DIRECTORY`, then `.specify/feature.json`. If neither
   declares one, **refuse and name both sources.** Never read the git branch —
   it is not what Spec Kit reads either.
2. Read the item with `speckit.github-lifecycle.inspect` and `gh`: its delivery
   state, its labels, its open blockers, and its children's delivery states.
3. Then:

```bash
{SCRIPT} \
  --issue <number> --state "<delivery state>" --type <item type> \
  --blocked-by <ref> ... --child-state "<state>" ... \
  --feature-dir <path if one exists>
```

`--format json` for the same fields as a parsed object.

## Report

The item's state and type, every refusal the policy raises, the next
transition with the evidence it takes, and the next workflow step.

Report `unverifiable` as it is given. Those are steps whose completion cannot
be read off the working tree because they produce nothing nameable. Saying "we
could not tell" is the answer; presenting a guess as a finding is not.

## Never

- Write anything. Not a transition, not a comment, not a file. Every other
  command in this namespace changes something; this one is the one that does
  not, and that is the whole reason to reach for it.
- Read the git branch to decide which item this is.
- Report a state you did not read. If the board could not be reached, say so
  and stop rather than routing from a state you assumed.

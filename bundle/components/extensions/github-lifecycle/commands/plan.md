---
description: Preview what a GitHub lifecycle transition requires, without applying it.
scripts:
  py: scripts/transition_plan.py
---

# GitHub Lifecycle Plan

Answer what a transition would take, before anyone commits to it. Reads and
decides; `transition` applies.

Run:

```bash
{SCRIPT} \
  --repo <owner>/<name> \
  plan --issue <number> --to "<target state>"
```

Writes nothing. `--out <path>` writes the preview to a file when someone wants
it in front of them, and is the exception rather than the shape of the command.

The script validates the transition against the installed state machine and
refuses an edge it does not define, naming the legal targets instead. It
refuses to start an item whose blockers are unfinished, to complete one whose
children are not complete, and to complete one informed by a prototype or spike
with no disposal record. Those refusals are the value here. Do not work around
one; report it.

## Report

State the transition, the state it must be applied against, the authority it
requires, and the evidence that authority expects. The state is what
`transition --expect` will be given, and applying refuses if the board has
moved since — so a preview taken long before the apply is worth taking again.

## Never

- Apply what this previews. That is `transition`.
- Treat the preview as an approval. It records what a transition would need,
  not that anybody agreed to it. The approval is the gate, and what a person
  approved is what `--expect` names.
- Preview more than one transition at a time. One answer, one change.

---
description: Plan GitHub lifecycle changes without applying them.
scripts:
  py: scripts/transition_plan.py
---

# GitHub Lifecycle Plan

Produce a written, reviewable plan for exactly one transition. Planning reads
and decides; applying is a separate command against the artifact this writes.

Run:

```bash
{SCRIPT} \
  --repo <owner>/<name> \
  plan --issue <number> --to "<target state>" \
  --out .specify/github-lifecycle/plans/<descriptive-id>.md
```

Write exactly `.specify/github-lifecycle/plans/<descriptive-id>.md`.

The script validates the transition against the installed state machine and
refuses an edge it does not define, naming the legal targets instead. It also
refuses to complete an item whose children are not complete. Do not work around
either refusal; report it.

## Report

State the transition, the authority it requires, and the evidence that
authority expects. The plan records the value it observed, and applying will
refuse if that value has changed since — say so, so the reviewer knows the plan
has a shelf life.

## Never

- Apply the plan. That is `transition`, after a human has approved this.
- Edit a plan file by hand. A plan is evidence of what was decided; changing it
  after approval means the approval covered something else.
- Plan more than one transition per file. One approval, one change.

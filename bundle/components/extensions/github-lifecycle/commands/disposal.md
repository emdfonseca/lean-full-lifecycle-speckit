---
description: Validate the disposal decision for a prototype or spike.
---

# GitHub Lifecycle Disposal

Decide what becomes of what a prototype or spike produced, before the work it
informed can complete.

```bash
python .specify/extensions/github-lifecycle/scripts/disposal.py \
  --record .specify/lifecycle/disposal/<issue>-<id>.md
```

## Why this exists

Nobody decides to ship prototype code. It is left in place because deleting it
needs a reason and keeping it needs none, and by the time anyone notices it is
load-bearing. Requiring the decision inverts that.

`artifact-policy.yml` has classed prototypes `ephemeral` with
`promote_only_by_explicit_decision` from the start. This is what makes that
enforceable: `plan` refuses Output Done for an item labelled `prototype` or
`spike` until a record exists.

## Report

State the decision and what it means for the artifacts.

- **delete** — name them; a reader must be able to check the removal happened.
- **archive** — kept as evidence, outside any build, not importable.
- **promote** — requires an approver and a reason. Neither is guessable, and
  defaulting either would make the deliberate decision automatic again.

`unresolved` is a legitimate finding. A prototype that answered nothing has
still told you something; silence has not.

## Never

- Record `promote` without naming who approved it and why.
- Leave findings empty because the answer was disappointing.
- Delete or archive without naming the artifacts.

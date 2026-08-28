---
description: Yours to run — perform exactly one next lifecycle step, then stop.
scripts:
  py: scripts/router.py
---

# Work Continue

Do the **one** thing this item needs next. Then stop and report.

One step, not the rest of the item. A command that ran until it finished would
be `specify workflow run` without the gates, and the gates are the part worth
keeping.

## How to decide

```bash
{SCRIPT} --issue <number> --state "<delivery state>" --type <item type> \
  --blocked-by <ref> ... --child-state "<state>" ... \
  --feature-dir <path if one exists>
```

The router reads `state-machine.yml` and `item-types.yml` and never the board,
so read the board first — `speckit.github-lifecycle.inspect` for the state and
`gh` for labels, blockers and children — and pass what you read.

**A non-empty `refusals` ends the run.** Report each one and stop. A refusal is
a finding, not an obstacle to work around, and none of them is yours to
override.

## What one step means at each state

The router names the workflow and the step; `item-types.yml` decides which
workflow, per type and state. What follows is what that resolves to, and it is
here to be read, not to be applied from memory — the file is authoritative.

- **At the entry state**, triage: assess the item, interpret it against its
  type's required content, gate, then transition. Refuse an observation with no
  reproduction and no stated outcome.
- **At the refining state**, produce and validate a readiness verdict with
  `speckit.github-lifecycle.readiness`, gate, then transition. Refuse an item
  with an open blocker.
- **At the startable state**, transition into delivery and run `speckit.specify`
  — which is where the feature directory first exists.
- **In delivery**, the next unfinished step of the item's delivery workflow.
- **At the terminal delivery state**, the outcome axis, and only for a type
  whose `carries_outcome` is true.

An Epic is decomposed, never specified. `item-types.yml` says which types are
decomposable; do not infer it from the name.

## What "unfinished" means, and what it cannot mean

A workflow step declares what it `produces`. If that artifact is in the feature
directory, the step is done. That is the only source of progress there is,
because this surface persists none of its own — no `state.yml`, no session
record. The board holds the delivery state and the tree holds the artifacts.

Steps that produce nothing nameable — gates, verify, the ratchet, converge —
come back as `unverifiable`. **Read the issue and the tree to decide those**,
and say which you judged by hand. A step reported as unverifiable and then
described as complete is exactly the false record this bundle refuses.

## Every transition goes through the guard

Perform transitions with `speckit.github-lifecycle.transition` and its
`--expect`, never by another route. Two worktrees on one item are caught there
and nowhere else.

## Never

- Perform two steps because the first was small.
- Continue past a refusal, or retry it with different inputs to clear it.
- Transition without `--expect`, or set a delivery state from issue closure.
- Read the git branch to decide which item this is.

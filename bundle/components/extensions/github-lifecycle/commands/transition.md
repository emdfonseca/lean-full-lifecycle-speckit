---
description: Apply one approved GitHub lifecycle field transition.
scripts:
  py: scripts/transition_plan.py
---

# GitHub Lifecycle Transition

Apply exactly one approved transition and read it back.

Requires an approved plan written by `plan`. Do not proceed without one.

Run:

```bash
{SCRIPT} \
  --repo <owner>/<name> \
  apply --plan <approved plan path> \
  --evidence <key>=<value> ...
```

Approved plan: `.specify/github-lifecycle/plans/<descriptive-id>.md`

Supply one `--evidence` for each item the plan lists. The script refuses the
write when any is missing, and names what is absent. Assert only evidence that
is true; the audit record is what a reviewer will read afterwards.

Use `--dry-run` first when the transition is consequential. It prints the exact
call and performs nothing.

## Report

State the value before and after, and the operation id. The script reads back
after writing and fails loudly if the result disagrees — a write that reports
success while the read disagrees is not a success.

## Never

- Mutate without an approved plan, or with a plan whose path you did not verify.
- Retry a refused transition with different evidence to get past it. A refusal
  is a finding to report, not an obstacle.
- Infer that work is complete because an issue was closed. Closure follows the
  delivery state and never sets it.
- Change more than the one value the plan names.

## What the audit adds

`transition_plan.py audit` compares the board to the policy, and also to the
working tree. A tree carrying tracked modifications while no open item is
`In Progress` is reported as `working tree: ...`, because `Ready` → `In
Progress` takes the evidence `work_started` and that means nothing if the work
started first.

It reports rather than refuses. An extension `events:` guard could refuse an
agent's tool call, but `specify bundle install` does not arm one — the user
must run `specify integration upgrade --force` — so a bundle cannot ship
prevention here. Inside a workflow the ordering *is* enforced, and
`INV-BUILD-AFTER-IN-PROGRESS` asserts it.

Untracked files do not count: a scratch file is not evidence that delivery
began. Git being unable to answer is reported as unknown rather than as clean.

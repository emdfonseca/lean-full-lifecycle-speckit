---
description: Apply one approved GitHub lifecycle field transition.
---

# GitHub Lifecycle Transition

Apply exactly one approved transition and read it back.

Requires an approved plan written by `plan`. Do not proceed without one.

Run:

```bash
python .specify/extensions/github-lifecycle/scripts/transition_plan.py \
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

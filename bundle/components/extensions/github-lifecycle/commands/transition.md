---
description: Apply one approved GitHub lifecycle field transition.
scripts:
  py: scripts/transition_plan.py
---

# GitHub Lifecycle Transition

Apply exactly one approved transition and read it back.

Run:

```bash
{SCRIPT} \
  --repo <owner>/<name> \
  apply --issue <number> --to "<target state>" \
  --expect "<the state a person approved this against>" \
  --evidence <key>=<value> ...
```

`--expect` is the guard. The write is refused when the board is no longer in
that state, because a run that overwrites a change it never saw is how two
people working in parallel lose one of them. It replaced a plan file that
recorded the same value: the file claimed to be a durable approval record and
was not, since `.specify/` is gitignored and each one was read exactly once, by
the apply that ran seconds after it was written.

Supply one `--evidence` for each item the transition requires. The script
refuses the write when any is missing, and names what is absent. It also
refuses a value that denies its own key — `--evidence required_ci_green=false`
is not an assertion of anything.

Assert only evidence that is true. Nothing verifies it for you, which is
exactly why there is one item left rather than five: what cannot be derived is
worth asking, and what the workflow already enforces is not worth retyping.

Use `--dry-run` when the transition is consequential. It prints the exact call
and performs nothing. `plan` previews what a transition needs without touching
anything.

## Report

State the value before and after, and the operation id. The script reads back
after writing and fails loudly if the result disagrees — a write that reports
success while the read disagrees is not a success.

## Never

- Mutate without the approval `--expect` names. The flag records what a person
  agreed to; supplying the current value to get past a refusal defeats it
  entirely.
- Retry a refused transition with different evidence to get past it. A refusal
  is a finding to report, not an obstacle.
- Infer that work is complete because an issue was closed. Closure follows the
  delivery state and never sets it.
- Change more than the one value the transition names.

## Posting the record

`--comment <path>` posts a file as an issue comment after the transition
succeeds, never before: a comment describing a transition that was then refused
is a false record. It rides on the transition because that already sits behind
a gate, already names what it expects, and already writes to this issue.

This is the record a later reader is told to trust over re-deriving the work.

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
started.

---
description: Validate a readiness verdict before an item may become Ready.
scripts:
  py: scripts/readiness.py
---

# GitHub Lifecycle Readiness

Check that a readiness verdict is real evidence rather than an assertion.
`state-machine.yml` requires one for Refining to Ready; this is what makes that
requirement mean something.

Run:

```bash
{SCRIPT} \
  --verdict <verdict path> \
  --issue <number> --repo <owner>/<name> \
  --record

{SCRIPT} \
  --from-record --issue <number> \
  --emit .specify/lifecycle/readiness-<run id>.md
```

`--issue` says which item. `--repo` opts into fetching it and linting its
acceptance criteria; without it the verdict is validated and nothing is
fetched.

## One judgement per item

`--record` stores the validated verdict against the issue. `--from-record`
reads it back, and refuses when none was recorded — an item that reached
delivery without being refined is exactly what that catches, and an absent
verdict is not a passing one.

Every other artifact here is keyed by run, which is right for a record of a
run. A readiness judgement is about the *item*, and outlives the run that made
it. Keyed by run, `lifecycle-story-delivery` could not name the verdict
`lifecycle-refine` had written, so it made a second one — unvalidated, and the
one the Output Done decision rested nearest to.

`--emit` writes the verdict where a gate can show it, because a gate needs a
path inside its own run. Recording a second verdict for an item replaces the
first: an item has one current readiness judgement, not one per attempt.

## Report

Two kinds of finding, and they are not the same.

**BLOCKING** — the verdict does not satisfy its schema, or it claims readiness
while holding open questions. The item stays in Refining. Report what is wrong
and stop; do not propose a transition.

**ADVISORY** — the item's acceptance criteria are hard to verify. Report them
so the author can improve them. They do not block Ready, because judgement
about prose belongs to a person.

## Never

- Edit the verdict to make it pass. The verdict records an assessment; changing
  it to clear a check falsifies the assessment.
- Treat an advisory finding as a blocker, or a blocker as advisory.
- Proceed to plan a transition when the exit status is non-zero.

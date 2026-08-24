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
  --issue <number> --repo <owner>/<name>
```

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

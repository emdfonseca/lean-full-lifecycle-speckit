---
description: Drivers and workflows — report an Epic's decomposition horizon and create approved children.
scripts:
  py: scripts/decompose.py
---

# GitHub Lifecycle Decompose

Decomposition is rolling-wave. The horizon is a **target count of Ready
children**, not a time window, so the amount of planning follows how much work
is actually startable rather than the calendar.

Read the horizon first. This writes nothing:

```bash
{SCRIPT} \
  --repo <owner>/<name> --epic <number> --target <n> status
```

The report distinguishes children that are Ready, done, and in flight, and says
which of two things to do. **Creating children does not fill the queue —
refining them to Ready does.** An Epic short of its target whose existing
children are all unrefined needs refinement, not more decomposition.

Create only from an approved proposal file:

```bash
{SCRIPT} \
  --repo <owner>/<name> --epic <number> --target <n> \
  apply --proposals <approved proposals path>
```

Each proposal is searched for duplicates and checked against its type's content
contract before creation, then linked to the Epic and read back. Nothing beyond
the horizon is created, however much was proposed; the surplus is reported as
deliberately undecomposed.

## Report

State what was created, what was skipped and why, and what was left
undecomposed. Undecomposed scope is a decision, not an omission, and a reader
needs to see it was deliberate.

## Never

- Create children without an approved proposal file. Creation is the least
  reversible operation here.
- Propose past the horizon to "save a round". The horizon exists because
  planning ahead of evidence gets redone.
- Mark new children Ready. They begin Inbox and earn Ready through a readiness
  verdict, which is a separate decision by a different authority.

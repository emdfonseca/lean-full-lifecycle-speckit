---
description: Route a discovery to capture, invalidate, retire or exception without leaving the item.
scripts:
  py: scripts/router.py
---

# Work Change

Something turned up that is not what you are working on. Record it and stay
where you are.

The item you are on **does not move**. That is the whole point of this command:
without it, recording a discovery means abandoning the item, and so the
discovery goes unrecorded.

## The four routes

| Route | What it does | Effect on the board |
|---|---|---|
| capture | `speckit.github-lifecycle.capture` creates a backlog item | a new item at the entry state |
| invalidate | marks an existing item as no longer true | none |
| retire | `speckit.github-lifecycle.retire` ends an item that was never delivered | that item to the retirement state |
| exception | `speckit.github-lifecycle.exception` validates and records one | none; creates no item |

**Choosing the route is a person's judgement, not yours.** Present what you
found and which route it looks like, and let a person say. Classifying which
authority a discovery belongs to is explicitly out of scope here.

## Capture refuses a duplicate

`capture` searches before it creates. When it reports candidates, **report them
and create nothing.** A second issue for a known problem is worse than no
issue: it splits the record.

## Retire is not finish

Retirement ends an item that was never delivered, and it must never be made to
look like completion. `state-machine.yml` gives it its own evidence —
`retirement_route` and `retirement_reason` — for that reason. An item that was
built goes to the terminal delivery state through `speckit.work.finish`.

## Never

- Move the item you are working on. Any of these four routes acting on it would
  be the one thing this command exists to avoid.
- Pick the route yourself when a person is available to pick it.
- Create an item `capture` has told you already exists.

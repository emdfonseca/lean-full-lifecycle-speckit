---
description: Retire a Story that will not be delivered, or supersede one another carries.
scripts:
  py: scripts/retire.py
---

# GitHub Lifecycle Retire

End an item without delivering it. `state-machine.yml` declares the routes:
`not_planned` for work decided against, `duplicate` for work another item now
carries. Both set no delivery state, because requiring one the work did not
earn is how a board starts recording fiction.

```bash
{SCRIPT} \
  --issue <n> --route <not_planned|duplicate> --reason "<why>" \
  [--superseded-by <n>]
```

## Report

State the route, the reason, and — for a supersession — the item that now
carries the work. `delivery_state_unchanged` is in every result so a reader
never has to infer that this was not a delivery.

## What it refuses

**A retirement with no reason.** The reason is the only part a later reader can
act on; without it a retirement is indistinguishable from an abandonment.

**A supersession naming nothing.** `--superseded-by` is required with
`--route duplicate`. Without the reference the work has been lost rather than
moved, and GitHub's `duplicate` marking says nothing about where it went.

**An item with open children.** Closing it would leave them under something
that no longer carries work. The refusal names them; close or reparent them
first.

Each refusal happens before any write. A route the policy does not declare is
rejected without touching the API at all.

## Never

- Use this to complete work. `transition` is what reaches Output Done, and a
  second route there would be an unaudited one.
- Retire an item to clear it from the queue. The queue is a symptom; a
  retirement is a decision about the work.
- Supersede without reading the successor. If it does not actually carry the
  work, the supersession has lost it.

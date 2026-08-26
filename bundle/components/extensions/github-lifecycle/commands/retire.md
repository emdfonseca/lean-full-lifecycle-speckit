---
description: Retire a Story that will not be delivered, or supersede one another carries.
scripts:
  py: scripts/retire.py
---

# GitHub Lifecycle Retire

End an item without delivering it. `state-machine.yml` declares the routes:
`not_planned` for work decided against, `duplicate` for work another item now
carries. Neither sets a delivery state, because requiring one the work did not
earn is how a board starts recording fiction — and because `transition` is the
only command that writes one, so a second route here would be unaudited.

**The delivery state is moved separately, to `Retired`.** An item abandoned at
`Refining` or `In Progress` and left there goes on claiming somebody is working
on it, which the audit reports and no forward transition can fix (#160). So a
retirement is two audited steps:

```bash
{SCRIPT-plan} --issue <n> --to Retired --out <plan>   # then apply it
{SCRIPT} --issue <n> --route <route> --reason "<why>"
```

Order matters: move first, then close. `Retired` is terminal, so nothing
follows it.

```bash
{SCRIPT} \
  --issue <n> --route <not_planned|duplicate> --reason "<why>" \
  [--superseded-by <n>] [--dry-run]
```

`--dry-run` applies every refusal, describes the calls it would make, writes
nothing, and reports the route and reason it would have applied. It does not
read back a close it did not perform, so the preview is usable before the
retirement rather than only after it.

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

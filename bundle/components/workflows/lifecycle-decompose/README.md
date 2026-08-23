# Decompose to the Horizon

Breaks an Epic into enough bounded children to meet a target of Ready children,
and no further.

```
read horizon -> decide -> propose -> gate -> create -> report
```

The horizon is a count of **Ready** children, not of children. Creating an item
does not make work startable; refining it does. So an Epic short of its target
whose existing children are all unrefined needs refinement rather than more
decomposition, and the workflow says so instead of creating more.

Nothing beyond the horizon is created, however much is proposed. The surplus is
reported as deliberately undecomposed, because leaving scope unplanned is a
decision a reader should be able to see.

## Inputs

| Input | Purpose |
|---|---|
| `epic_ref` | the Epic to decompose |
| `target_ready_count` | how many Ready children are wanted |
| `proposal_verdict` | reviewer's approval of the proposed children |

## What it will not do

Create children without an approved proposal file, create past the horizon, or
mark anything Ready. New children begin Inbox and earn Ready through a
readiness verdict, which is a different decision by a different authority.

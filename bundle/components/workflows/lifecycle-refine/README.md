# Refine to Ready

Takes one item from Refining to Ready through a readiness verdict that is
validated rather than asserted.

```
inspect -> assess -> validate -> gate -> plan -> gate -> apply -> report
```

Two gates, because two different decisions are being made: whether the item is
ready, and whether to apply the change that records it. The first is a product
judgement, the second an engineering one, and `state-machine.yml` gives them
different authorities.

Stops in Refining when the verdict holds a blocking question. That is the
intended outcome, not a failure: an item nobody can start is better described
than moved.

## Inputs

| Input | Purpose |
|---|---|
| `issue_ref` | the item to refine |
| `readiness_verdict` | reviewer's verdict on readiness |
| `transition_verdict` | reviewer's approval of the planned change |
| `integration` | agent integration, defaults to `opencode` |

## What it will not do

Move an item to Ready without a schema-valid verdict, apply a plan a reviewer
has not seen, or write more than the single field the plan names.

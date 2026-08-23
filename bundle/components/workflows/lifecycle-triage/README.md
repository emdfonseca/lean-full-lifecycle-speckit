# Triage an Incoming Item

Decides what an item is, not when it will be done.

```
assess -> interpret -> gate -> plan -> transition -> report
```

Triage moves an item from Inbox to Refining and no further. Ready requires a
readiness verdict, which is a separate decision by a different authority, and
the script refuses any other target rather than trusting the workflow to stay
in its lane.

Three things it will not do: convert an observation with no reproduction and no
stated outcome into work, record behaviour read from code as though it were
intended, or commit a priority. Each is a way a backlog stops being trustworthy.

## Inputs

| Input | Purpose |
|---|---|
| `issue_ref` | the item to triage |
| `triage_verdict` | reviewer's approval of the assessment |

## What it will not do

Reach Ready, create an item, or write a field before the assessment is
approved.

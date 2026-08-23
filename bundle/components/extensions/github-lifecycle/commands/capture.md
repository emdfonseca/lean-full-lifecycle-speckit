---
description: Deduplicate and create an approved backlog finding.
---

# GitHub Lifecycle Capture

Record a finding without making the backlog less trustworthy. Findings arrive
mid-flight, during delivery or review or an incident, and losing them is silent
— but recording them carelessly produces a backlog nobody reads.

Search first:

```bash
python .specify/extensions/github-lifecycle/scripts/capture.py \
  --repo <owner>/<name> --title "<proposed title>"
```

This writes nothing. Report the candidate duplicates and their scores, closed
ones included: something already fixed, rejected, or decided is exactly what a
duplicate report is for.

Create only after a person has seen the candidates and said to proceed:

```bash
python .specify/extensions/github-lifecycle/scripts/capture.py \
  --repo <owner>/<name> --title "<title>" --type <story|bug|spike> \
  --body "<body meeting the type's content contract>" --create
```

The script refuses to create when a candidate duplicate exists, or when the
body lacks what the type requires. Both refusals are findings to report, not
obstacles to work around by raising the threshold.

## Creating also places the item on the board

Pass `--project <n>`. Delivery state lives on the board, and every transition,
the audit, and the refinement queue read it from there. An item created off the
board exists and cannot be moved, which is worse than not creating it: it looks
filed.

If placement fails the result says `on_board: false` with the reason. Report
that. A creation that reads as clean while the item cannot be transitioned is
the failure this reporting exists to prevent.

Organization Issue Fields carry state on the issue itself, so there is no board
to be off. That case is reported too, and is not a failure.

## Distinct from `speckit.taskstoissues`

That command converts a feature's `tasks.md` into dependency-ordered issues:
implementation decomposition inside a feature. This captures a finding into the
backlog with a duplicate search. Do not use one for the other's job.

## Never

- Create without searching.
- Raise `--threshold` to get past a duplicate report. Decide instead: link to
  the existing item, or state why this is genuinely different.
- File an observation with no reproduction and no stated outcome. That is a
  discovery note, and the script will say so.

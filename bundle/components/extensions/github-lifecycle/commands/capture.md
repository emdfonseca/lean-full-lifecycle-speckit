---
description: Drivers and workflows — deduplicate and create an approved backlog finding.
scripts:
  py: scripts/capture.py
---

# GitHub Lifecycle Capture

Record a finding without making the backlog less trustworthy. Findings arrive
mid-flight, during delivery or review or an incident, and losing them is silent
— but recording them carelessly produces a backlog nobody reads.

Search first:

```bash
{SCRIPT} \
  --repo <owner>/<name> --title "<proposed title>"
```

This writes nothing. Report the candidate duplicates and their scores, closed
ones included: something already fixed, rejected, or decided is exactly what a
duplicate report is for.

Create only after a person has seen the candidates and said to proceed:

```bash
{SCRIPT} \
  --repo <owner>/<name> --title "<title>" --type <story|bug|spike> \
  --body "<body meeting the type's content contract>" --create
```

The script refuses to create when a candidate duplicate exists, or when the
body lacks what the type requires. Both refusals are findings to report, not
obstacles to work around by raising the threshold.

## Recording the decision a person made

A duplicate report is a question for a person, and the answer belongs in the
record rather than in whoever remembers making it:

```bash
{SCRIPT} \
  --repo <owner>/<name> --title "<title>" --type <story|bug|spike> \
  --body "<body>" --considered <n> --considered <n> --create
```

Every candidate the search raised must be named. Not any — every. A flag that
cleared the whole report once one item was named would let the second duplicate
through unseen, which is what the report exists to prevent. The refusal lists
the exact flags to add, so the answer is never a guess.

A number the search did not raise is refused too. A decision recorded against
an item nobody surfaced is either a typo or a comparison against something
else, and both should be corrected before the record is written.

The numbers travel into the result as `considered`, which is what makes the
decision readable afterwards rather than a flag somebody once passed.

This follows how the extension records every other human decision: a structured
record passed by flag, as with `ratchet --exception` and
`sensitive --authorization`.

## Creating also places the item on the board

Pass `--project <n>`. Delivery state lives on the board, and every transition,
the audit, and the refinement queue read it from there. An item created off the
board exists and cannot be moved, which is worse than not creating it: it looks
filed.

Placing the row is half of it. The item is also given the delivery state a new
item enters, taken from the `state-machine.yml` edge that starts from no state
— the one whose evidence is `issue_exists`, which creation has by construction.
A row with no delivery state is reported by the audit, skipped by the
refinement queue, and cannot be planned from, so a capture that stopped at
placement would file something nothing downstream can see.

The result carries `delivery_state`. If placement fails it says
`on_board: false` with the reason; if placement succeeds and the state write
fails it says `on_board: true` with `delivery_state: null` and what that means.
Report either. A creation that reads as clean while the item cannot be
transitioned is the failure this reporting exists to prevent.

Organization Issue Fields carry state on the issue itself, so there is no board
to be off. That case is reported too, and is not a failure.

## Marking what the finding makes wrong

A discovery that breaks an Epic's shape, filed as an ordinary sibling, leaves
that Epic unmarked — and the next person to read it is reading something known
to be wrong.

```bash
{SCRIPT} ... --create \
  --invalidates <n> --invalidates <n> \
  --invalidation-reason "what about those items is no longer true"
```

Each named item gets a comment naming the new issue and the reason. The reason
is required: a comment saying an item is invalidated without saying why is a
mark nobody can act on.

**The check runs before creation and the comments after it.** A closed target
is refused while there is still nothing to undo, so a run never leaves a
created issue alongside a refusal. The comments are posted only once the new
issue has been created and read back, because a comment pointing at a number
that does not exist is a false record.

A closed item is refused rather than commented on. It has already been decided;
if the decision was wrong, reopen it deliberately.

Without `--create` nothing is written to any issue. The search path returns
before any of this.

**It marks and stops.** Whether the invalidated item should be retired,
respecified, or left alone is a person's judgement, and the comment says so.

## Distinct from `speckit.taskstoissues`

That command converts a feature's `tasks.md` into dependency-ordered issues:
implementation decomposition inside a feature. This captures a finding into the
backlog with a duplicate search. Do not use one for the other's job.

## Never

- Create without searching.
- Raise `--threshold` to get past a duplicate report. It hides the report
  rather than answering it. Decide instead: link to the existing item, or
  record the comparison with `--considered`.
- File an observation with no reproduction and no stated outcome. That is a
  discovery note, and the script will say so.
- Decide what happens to an invalidated item. `--invalidates` records that it
  is wrong; retiring or respecifying it is a separate decision a person makes.
- Comment on an invalidated item before the new issue exists, or by any route
  other than `--invalidates`. The ordering is what keeps the comment true.

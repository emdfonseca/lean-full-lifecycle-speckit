---
description: Take a delivered item to Output Done and close it.
scripts:
  py: scripts/router.py
---

# Work Finish

The last step, and the one with the most ways to record something false.

## In order

1. **Check the acceptance criteria hold.** Each one, against what was built.
   This is what the transition's evidence asserts and nothing else verifies it.
2. **Run the project's validators.** Whatever the project defines; a workflow
   aborts on a non-zero step and this has no workflow to abort it, so a failing
   validator ends the run here.
3. **Check the ratchet** with `speckit.github-lifecycle.ratchet`.
4. **Route**, and stop on any refusal:

```bash
{SCRIPT} --issue <number> --state "<delivery state>" --type <item type> \
  --child-state "<state>" ...
```

   A decomposable item with a child that is not terminal is refused here.
   `item-types.yml`: its progress derives from its children, so completing it
   independently of them makes the derivation decorative.
5. **Write the delivery record** — what was built and what it exposed. This is
   the comment a later reader is told to trust instead of re-deriving the work,
   so it carries what the work revealed, not a restatement of the issue.
6. **Transition and comment in one call**, so a record of a refused transition
   never exists:

```bash
speckit.github-lifecycle.transition apply --issue <n> \
  --to "<terminal delivery state>" --expect "<the delivery state>" \
  --evidence acceptance_criteria_satisfied=<what you checked> \
  --comment <path to the delivery record>
```

7. **Close as completed**, after the transition and never before. Closure
   follows the delivery state; it never sets it.

## What the evidence means

`acceptance_criteria_satisfied` is the one item left because it is the one
nobody can derive. Reaching this point already means the validators and the
ratchet passed. Asserting it without having checked each criterion is the
failure this whole surface is built to make harder, and nothing downstream can
catch it.

## Never

- Close first and transition after. The audit reports that, and it is a board
  recording fiction.
- Assert evidence you did not check.
- Finish a decomposable item whose children are not all terminal.
- Post the delivery record before the transition succeeds.
- Use this to retire. Retirement is `speckit.work.change`, and it carries its
  own evidence because it is not completion.

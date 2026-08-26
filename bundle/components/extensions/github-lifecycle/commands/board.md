---
description: Create the Projects v2 board a project-scoped deployment needs.
scripts:
  py: scripts/board.py
---

# GitHub Lifecycle Board

ADR 0003 makes project-scoped fields the default and organization Issue Fields
the opt-in. Nothing created the default, so a greenfield bootstrap into an
ordinary repository produced a backlog nothing could transition —
`delivery_state` lives on a board that did not exist.

```bash
{SCRIPT} --repo <owner>/<name> [--title <title>] [--dry-run]
```

## Adding a state to a board already in use

When `state-machine.yml` gains a state, an existing board has to be given the
option or nothing can hold it:

```bash
{SCRIPT} --repo <owner>/<name> --project <number> [--dry-run]
```

Options already present keep their **ids**. That is the whole of it: an item's
stored value is an option id, not a name, so sending the surviving options by
name alone makes GitHub mint new ids and every item's value dangles. Doing this
by hand cleared the delivery state of 160 items once (#163).

Removing an option the policy no longer declares is refused, not performed —
that clears it from every item holding it, which is a decision about those
items. A board already matching the policy is not written to at all.

Explicitly invoked, never implicit. Creating a board decides where a project's
work is tracked, and a bootstrap that did it quietly would be making that
decision on the project's behalf.

## The Status field already exists

Every new board carries a single-select named `Status` with GitHub's own
`Todo` / `In Progress` / `Done`. The name is **reserved**, so creating one
fails — `Name cannot have a reserved value` — and the existing field is
reshaped instead. Its options are replaced wholesale with the states
`state-machine.yml` declares, in the policy's order.

Replaced rather than added to, deliberately: a board left carrying `Todo`
alongside the real states would let an item hold a value the state machine does
not know.

## Linking is not populating

Linking a project to a repository does not put the repository's issues on it.
A board created after the backlog leaves every existing item off, invisible to
the queue and to the audit — an empty board reads exactly like a working one.

The result carries `issues_not_on_the_board`. Report it. Pass `--adopt` to
place them:

```bash
{SCRIPT} --repo <owner>/<name> --adopt
```

Reported by default and placed only when asked, for the same reason the board
is not created implicitly: which items belong on a board is the project's
decision.

## Report

State the board number, the field, its options, and whether an existing field
was reshaped. Report `linked_to` — a board that is not linked to the repository
is one the other commands will not find.

## What it refuses

**A second board.** `authoritative_project_count` is 1. If the owner already
has one, the ambiguity is reported and nothing is written; pass `--project` to
use it, or decide which is authoritative.

**A half-made board.** If the field cannot be added or reshaped, or the link
fails, that is reported rather than returned as success. A board that exists
and cannot carry a state is worse than no board, because `doctor` will find it
and stop looking.

The board is read back after writing — the field is fetched again and its
options compared to the policy. Three writes that each returned zero are not a
working board.

## Never

- Run this to "fix" a repository whose board exists but is misconfigured. It
  creates; it does not repair.
- Add the states to the default options rather than replacing them.
- Create a board because inspection reported an ambiguity. Read the ambiguity
  first: more than one board is a different problem from none.

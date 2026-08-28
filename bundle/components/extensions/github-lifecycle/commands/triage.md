---
description: Drivers and workflows — assess an incoming item and propose what happens to it next.
scripts:
  py: scripts/triage.py
---

# GitHub Lifecycle Triage

Decide what an item *is*. Not when it will be done — that is a different
decision by a different person, and conflating them turns a triage queue into a
commitment nobody agreed to.

```bash
{SCRIPT} \
  --repo <owner>/<name> --issue <number> \
  --out .specify/lifecycle/triage-<run>.json
```

Writes nothing to GitHub. It reads the item, searches for duplicates, and
reports what a reviewer needs in order to decide.

A non-zero exit means something needs a person: a candidate duplicate, or an
item lacking the evidence its type requires.

## Report

State the proposed type, the candidate duplicates with their scores, and what
evidence is missing. Duplicate scores are advisory — items sharing a naming
convention will resemble each other, and the search raises candidates rather
than deciding.

Record any priority as a **recommendation with its reasoning**. Triage does not
commit roadmap dates or priorities.

Label behaviour read from code, with nothing agreeing it was wanted, as
inferred. A later reader cannot otherwise tell a decision from an observation.

## A security finding

A security finding is a Bug carrying the `security` label — not a fifth item
type. A separate type would fork every content contract, template and generator
for one boolean; the label plus a required Severity says the same thing and
nothing downstream has to learn a new shape.

```bash
{SCRIPT} \
  --issue <n> --severity <Critical|High|Medium|Low> --format json
```

What makes it different is the routing, not the marking. Report all of it:

- it carries a Severity **before** triage will propose `Refining`. Unclassified,
  it is indistinguishable from an ordinary bug in every queue that reads the
  board;
- it is reviewed by the security owner, not only the assigned engineering
  owner;
- it does not carry a working exploit in its body. State the class and the
  affected surface — a reproduction that is itself an attack has published it.

`recommended_severity` is a reading of the wording and nothing more. Pass
`--severity` for what the board actually carries. Triage decides what an item
is, never how bad it is; that is the security owner's call, the same split this
command already keeps for Priority. When the wording indicates nothing, there
is no recommendation rather than a default — a severity invented by a keyword
scan gets read later as an assessment.

## Never


- Move an item to Ready. Triage proposes Refining and nothing further; the
  script refuses any other target.
- Convert an observation into work. An item with no reproduction and no stated
  outcome is a discovery note, and filing it as work makes the backlog less
  trustworthy.
- Write a field before a reviewer has approved the assessment.
- Record inferred behaviour as an acceptance criterion.

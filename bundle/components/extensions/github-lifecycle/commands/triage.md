---
description: Assess an incoming item and propose what happens to it next.
---

# GitHub Lifecycle Triage

Decide what an item *is*. Not when it will be done — that is a different
decision by a different person, and conflating them turns a triage queue into a
commitment nobody agreed to.

```bash
python .specify/extensions/github-lifecycle/scripts/triage.py \
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

## Never

- Move an item to Ready. Triage proposes Refining and nothing further; the
  script refuses any other target.
- Convert an observation into work. An item with no reproduction and no stated
  outcome is a discovery note, and filing it as work makes the backlog less
  trustworthy.
- Write a field before a reviewer has approved the assessment.
- Record inferred behaviour as an acceptance criterion.

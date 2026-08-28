---
description: Workflows, not people — validate a bounded discovery record.
scripts:
  py: scripts/discover.py
---

# GitHub Lifecycle Discover

Check that a discovery record can be consumed. Prototype, spike, and the
uncertainty branch of story delivery all read it, and a consumer that reads
nine of eleven sections and proceeds is worse than one that stops: it produces
a confident answer from an incomplete picture.

```bash
{SCRIPT} \
  --record .specify/lifecycle/discovery-<run>.md
```

## Report

**BLOCKING** — the record does not satisfy its schema, or a section is empty.
An empty section is blocking because an absent finding and an uninvestigated
area look identical afterwards, and only one of them is safe to build on. Say
what was not found, or that the section does not apply.

**ADVISORY** — worth a reader's attention. Inferred observations that will need
reconciling, an absence of recorded uncertainty, or a scope that does not say
what was left out.

## What discovery is

Evidence, never intent. `artifact-policy.yml` classes it `evidence_ephemeral`:
it reports what is there, and what was wanted is a separate question answered
by a spec. Behaviour read from code is recorded as `inferred` and stays
inferred until reconciliation.

## Never

- Record an invented answer for an open question. An admitted question is
  better than a plausible guess, because the guess stops anyone looking.
- Promote an inferred observation to intended behaviour, or write one as an
  acceptance criterion.
- Modify anything outside the record.

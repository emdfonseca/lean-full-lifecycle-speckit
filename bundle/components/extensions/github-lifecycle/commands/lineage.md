---
description: Drivers and workflows — record what an item was derived from, and detect a spec changed out of band.
scripts:
  py: scripts/lineage.py
---

# GitHub Lifecycle Lineage

Record which artifacts an item was built against, so a spec edited afterwards
is visible rather than silent.

## Record, once the artifacts exist

```bash
{SCRIPT} record --issue <number> \
  --feature-dir <the item's feature directory> \
  --workflow <the workflow carrying it>
```

It hashes exactly what that workflow's steps declare they `produce`. There is
no list of artifact names in this command, which is the point: adding a
producing step to a workflow extends lineage with nothing to change here.

An artifact that does not exist yet is recorded as absent rather than left out.
A step that has not run and a step whose output was deleted look identical in a
record that simply omits the entry.

## Check

```bash
{SCRIPT} check --issue <number>
{SCRIPT} check --issue <number> --format json
```

Exit `1` when there is anything to report, so a gate can act on it.

Three findings, and they are not the same:

- **`OUT_OF_BAND_CHANGE`** — a recorded artifact's content differs from disk,
  or it was recorded and is now gone, or it appeared after the record was
  written. Names the file and the revision the record was taken at.
- **`ABSENT_LINEAGE`** — nothing was recorded for this item. Reported, never
  passed over: an unrecorded item is not an unchanged one, and returning "no
  drift" for a comparison that never happened is the failure this exists to
  prevent.
- Nothing — every recorded artifact still matches.

## What the audit adds

`transition_plan.py audit` runs this for every item in the delivering state,
and reports what it finds against that item.

That one state, deliberately. Earlier ones have no feature directory at all —
`speckit.specify` creates it on the way in — so asking them for lineage asks
about artifacts that cannot exist yet. Later ones cannot record it
retroactively. Either way the finding is one nobody can act on, and an audit
carrying a dozen of those is an audit people learn to skip.

Epics are exempt. Their artifacts are their children, and the parent/child
rules already cover those.

## This is not a delivery state

A lineage record holds file paths, hashes, and the git revision it was taken
at. Nothing in it says where an item is in the lifecycle, and nothing may read
it as though it did — the board holds that, and a second answer to it is
exactly what this must not become.

## Never

- Reconcile a stale artifact. Deciding what a changed spec means is a person's
  judgement; re-deriving an item from an edited spec would make that judgement
  without saying so. This detects and reports.
- Re-record to clear a finding. That overwrites the evidence that the artifact
  moved, which is the only thing anybody wanted to know.
- Treat an absent record as a passing one.

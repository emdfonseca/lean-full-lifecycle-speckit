# Product decisions

One entry per decision, carrying the four an ADR carries. An entry needing more
is an ADR and belongs in `docs/decisions/`, referenced from here.

## 2026-08-24 — Bootstrap stops at startable work

Status: accepted. Context: `AC-GREENFIELD-007` requires a bootstrap to stop
before implementing. Decision: nine backlog items created, none started.
Consequence: the first Story is startable and no product code exists.

## 2026-08-24 — Refuse organization schema mutation

Status: accepted (AR-08). Context: the backend resolved to organization Issue
Fields, where creating a field lands on every repository in the organization.
Decision: refuse rather than defer. Consequence: Outcome Status, Risk, Severity
and Capability have no field, so those transitions cannot be recorded.

## 2026-08-24 — Record decisions as unset rather than invent them

Status: accepted. Context: `outcome-policy.yml` requires ten fields and the
product context supplied none of the measurement ones. Decision: record them
unset. Consequence: outcome assessment is blocked, and no later measurement
compares against a number nobody chose.

## Open

- AR-17: what counts as a link, and how a target resolves. Blocks the core
  behaviour; no Story can be written until it closes.
- AR-02: the toolchain. Blocks verification, CI, and the ratchet.
- AR-16: what "single binary" means for a Python tool. Blocks the release path.
- AR-18: what corpus and hardware the two-second budget is measured against.
- AR-19: how "never modifies a note" is proven.

# Product decisions

One entry per decision, carrying the four an ADR carries. An entry needing more
is an ADR and belongs in `docs/decisions/`, referenced from here.

## 2026-08-25 — Adopt without changing behaviour

Status: accepted. Context: nothing was known about intent, and the test suite
is a behaviour sample rather than a specification. Decision: scan-mode adoption
only; no tracked file modified. Consequence: every finding is a reading, not a
measurement.

## 2026-08-25 — Keep the stale build paths

Status: accepted (EX-001, expires 2026-11-24). Context: `tox.ini`,
`.travis.yml` and `Makefile` all target versions the project dropped.
Decision: keep them. Consequence: the only record of how the project used to be
built survives, and `ci.yml` remains authoritative regardless.

## 2026-08-25 — Map `devbox run verify` to pytest by overlay

Status: accepted. Context: generating a script needs a stack decision nobody has
made. Decision: overlay to pytest, which the project already runs. Consequence:
`release-verify` stays unmapped until a release is in scope.

## Open

- Does a write commit on a non-shared connection? Unverified on every backend
  (F3).
- Should `Database.transaction` re-raise? The merged PR says yes; the code and
  its test say no (F1).
- Who owns the three exceptions? They are refused until named.

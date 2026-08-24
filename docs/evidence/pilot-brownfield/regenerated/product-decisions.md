# Product decisions

One entry per decision: what, when, who, and one line of why.

## 2026-08-24 — Adopt without changing behaviour

Owner: unassigned. Scan-mode adoption only. No tracked file was modified.
Why: nothing is known about intent yet, and a change made before that is a
guess.

## 2026-08-24 — Keep the stale build paths

Owner: unassigned (EX-001). `tox.ini`, `.travis.yml`, `Makefile` stay.
Why: removing them destroys the only record of how the project used to be
built, and `ci.yml` is the authoritative path regardless.

## 2026-08-24 — Map `devbox run verify` to pytest by overlay

Owner: unassigned. Why: generating a script needs a stack decision nobody has
made; pytest is what the project already runs.

## Open

- Does a write commit on a non-shared connection? Unverified on every backend
  (discovery F3).
- Should `Database.transaction` re-raise? The merged PR says yes; the code and
  its test say no (F1).

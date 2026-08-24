# Stack decision

## Status

Proposed. Nothing below is accepted: AR-02 is open, and the bootstrap refused
to choose a toolchain on the project's behalf.

## Context

The supplied product context named Python — "because the users already have
it" — and nothing else. `bootstrap-policy.yml` requires a recorded stack
decision before a verification script can be generated, so the absence blocks
`devbox run verify` and everything downstream of it.

## Decision

| Choice | Taken | Reason |
|---|---|---|
| Python | yes | supplied intent: the users already have it |
| Python version | **open (AR-02)** | decides which syntax and stdlib are available |
| Test runner | **open (AR-02)** | no verification command can be generated without it |
| Linter, type checker | **open (AR-02)** | two quality gates cannot produce a number |
| Packaging tool | **open (AR-02, AR-16)** | "single binary" has no native Python answer |
| A compiled language | no | would satisfy "single binary" and contradict supplied intent |

## Consequences

- `devbox run verify` cannot be generated, so the first delivery fails at a
  shell step until AR-02 closes.
- The ratchet has no baseline, and `quality-gates.yml` states a first run is
  not a pass.
- "Single binary" stays undecided, which leaves the release path undefined
  and `sbom_provenance_signing` unresolved.

# Brownfield scan run, against a real product

The no-target scan half of #104. Metrics: `docs/evidence/pilot-brownfield.md`.

| | |
|---|---|
| Run | `af600cc4`, `lifecycle-brownfield-adoption`, `scope_mode=scan` |
| Target | a dissociated clone of a private Chrome extension: 445 commits, pnpm workspace, `apps/` + `packages/`, `devbox.json`, 5 ADRs |
| Outcome | `completed`. Verdict in the report: **adopted, verification commands unresolved** |
| Operator | agent |

## Why this target

`#104` says a synthetic repository "cannot produce a legacy hotspot and would
make the stream report a pass it did not earn". The earlier scan in this
directory ran against `records`, a single-module library with no target
supplied. This one has real history, a workspace with two members, its own
documentation set, and its own agent instructions.

Prepared by cloning read-only from a local checkout, removing every remote, and
stripping the project's previous governance so adoption was not reconciling two
systems. That removal is a commit of its own, and the bundle install is another,
so the adoption diff is measurable against a clean tree.

## What holds

**AC1 — a no-target scan writes only framework records.** Measured by
`git status` after the scan step, not taken from the step's report:

```
?? .specify/lifecycle/
?? .specify/workflows/runs/
```

Nothing outside `.specify/`.

**AC5 — unrelated behaviour is preserved.** After the full run, one tracked
file changed:

```
 M .specify/memory/constitution.md
```

`PRODUCT.md` and `.specify/lifecycle/` are new. Every build path is
byte-identical: `devbox.json`, `pnpm-workspace.yaml`, every `package.json`,
`pnpm-lock.yaml`, `biome.json`, `.github/`, `.githooks/`, `apps/`, `packages/`.
**No product code was touched**, which is the criterion this stream exists for.

All seven declared documents were written and the set passes `documents.py`
with 0 problems.

## What this run proved about three open items

**#137 works on a real project.** `runbook.md` and `domain.md` were both
authored. Domain carries 24 terms with the "does not mean" column, which is the
section I argued earns the document. `PRODUCT.md` carries `Deliberately
untested`.

**#138's shape was chosen independently.** The agent wrote `architecture.md`
with `As built` and `Intended` as separate top-level sections, which is exactly
what #138 proposes and it does not know that issue exists. It reached the same
conclusion for the same reason: the arc42 names cannot carry the distinction.

**#136 works on a real project.** The verification step refused generation
because the constitution has "no `Recorded stack decisions` section". Before
#136 a non-empty constitution cleared that guard by existing.

## What did not hold

Five findings, all filed before being acted on, none fixed in place.

| # | What |
|---|---|
| 141 | The decision-record directory is hardcoded to `docs/decisions/`. The target keeps five ADRs in `docs/adr/`, invisible to the contract |
| 142 | A ratchet baseline records no scope. The target scopes coverage to `src/shared/store*`, so the number describes the store and the ratchet would enforce it as the whole |
| 143 | `sensitive.py --record` parses YAML before scanning and crashes on Markdown records, which is what its own documented example is |
| 144 | Approving the verification resolution performs nothing; no step consumes the gate's verdict |
| 145 | `establish-constitution` writes a constitution failing the contract on 13 counts, three principles with no RFC 2119 keyword at all |

## Two judgements made during the run

**I scanned the discovery record by hand before approving its gate.** `#143`
meant `sensitive.py` could not certify it. Rather than approve on the strength
of "it probably would have been fine", I ran the policy patterns over all 407
lines directly: zero findings, no `[redacted]` marker, patterns confirmed
loaded from policy. The record is clean because a scan says so, not because a
tool failed to say otherwise.

**I checked `pnpm verify` existed before choosing the overlay.** The step
proposed mapping `devbox run verify` to it. `package.json` defines
`verify: pnpm -r --workspace-concurrency=1 verify`, so the overlay names a real
command. An overlay pointing at a command that does not run would be worse than
no overlay. The choice of overlay over recording a stack decision follows from
what adoption means: the project already decided its stack, and `#136` should
not be satisfied by the framework inventing one.

## What this run did not cover

AC2, AC3, AC4 and AC6 need `scope_mode=targeted`, and AC6 additionally needs a
GitHub target, which this dissociated clone deliberately lacks. The stream is
not complete and the metrics record says so.

## Disposal

The clone is retained until this record is reviewed. It has no remotes, so
disposal is a directory delete with nothing to detach first.

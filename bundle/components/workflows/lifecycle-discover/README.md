# Bounded Discovery

Investigates a capability within a stated boundary and produces a record other
workflows can consume.

```
state scope -> investigate -> validate -> gate -> report
```

Scope is stated before anything is examined. Discovery that decides its own
boundary while running expands until someone stops it, and leaves a record
nobody can tell the edges of.

## Evidence, not intent

`artifact-policy.yml` classes discovery output `evidence_ephemeral`. It reports
what is there; what was *wanted* is a separate question answered by a
specification. Every behaviour observation is marked `specified` or `inferred`,
and inferred findings stay inferred until reconciled.

That distinction is the reason this workflow exists separately from the ones
that act on it. Prototype, spike, and story delivery all read this record, and
each must reconcile before asserting anything it contains.

## Every section appears

A section with nothing to report says so. An empty section and an absent one
look identical afterwards, and only one of them was investigated.

## Inputs

| Input | Purpose |
|---|---|
| `target` | the capability to investigate |
| `scope_note` | additional boundary the caller wants stated |
| `record_verdict` | reviewer's acceptance of the record as evidence |

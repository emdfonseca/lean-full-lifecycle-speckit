# Development tracking

Roadmap execution is tracked on GitHub rather than in a document, using the
mechanisms this bundle itself prescribes.

| What | Where |
|---|---|
| Repository | https://github.com/emdfonseca/lean-full-lifecycle-speckit (private) |
| Project board | https://github.com/users/emdfonseca/projects/3 |
| Phases | one Epic issue per roadmap phase, `P0a` through `P14` |
| Work items | Story issues, linked as native sub-issues of their Epic |

## Field model

`policy/github-schema.yml` prefers organization-level Issue Fields. This is a
personal repository, where custom Issue Fields and Issue Types are unavailable,
so the board runs the schema's documented fallback:
`when_issue_fields_unavailable`, with `authoritative_project_count: 1` and
`allow_status_labels: false`.

Every field the schema names exists as a Project v2 field: Delivery Status,
Outcome Status, Risk, Severity, Priority, and Capability. The schema is
therefore implementable as written, which was previously untested.

Two caveats:

- These are *Project* fields, not Issue Fields. They apply to items on the board,
  not to issues repository-wide. Moving to an organization would change the
  mechanism, not the model.
- The board also carries Projects' built-in `Status` field. It is unused and
  should stay unused; `Delivery Status` is authoritative. This is the duplicate
  hazard `github-schema.yml` warns about under `do_not_create_duplicate`.

## Outcome fields are deliberately empty

This work is tooling, not product. `Outcome Status` measures a business result
and does not apply to items like "refactor the validator". Leaving it unset is
honest; inventing outcomes to fill the field would prove the model works when
only half of it had been exercised.

Engineering state is tracked faithfully:
`Inbox → Refining → Ready → In Progress → Output Done`.

## Decomposition is rolling-wave

All 19 phases exist as Epics so the whole roadmap is visible. Only the near
horizon is decomposed into Stories, which is what `lifecycle-decompose`
requires: "propose only enough bounded Stories for the configured planning
horizon". Later Epics stay in `Inbox` until refined.

## Transitions are manual for now

The extension's GitHub commands are prose instructions to an agent until P3
builds the deterministic adapter. Until then, board transitions are performed by
hand and carry none of the plan/approve/mutate/read-back guarantees the bundle
promises. Once P3 lands, this repository becomes the first real target for that
adapter.

## Upstream defects

D8 and D9 are Spec Kit defects, filed and tracked locally:

| Defect | Upstream | Local |
|---|---|---|
| `bundle install` cannot install workflows from a catalog | github/spec-kit#4282 | #28 |
| `bundle install` does not scaffold extension config | github/spec-kit#4283 | #29 |

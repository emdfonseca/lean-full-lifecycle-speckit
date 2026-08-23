# Development tracking

Roadmap execution is tracked on GitHub rather than in a document, using the
mechanisms this bundle itself prescribes.

| What | Where |
|---|---|
| Repository | https://github.com/emdfonseca/lean-full-lifecycle-speckit (private) |
| Project board | https://github.com/users/emdfonseca/projects/3 |
| Phases | one Epic issue per roadmap phase, `P0a` through `P14` |
| Work items | Story issues, linked as native sub-issues of their Epic |
| Releases | Milestones, one per version in the roadmap's release sequence |

## Milestones are releases, not phases

Phases are already Epics. A milestone per phase would be a second copy of the
same grouping, which is the failure mode this repository spent P0d removing.

Releases are a genuinely different axis: several phases ship as one version.

| Milestone | Phases | Exit |
|---|---|---|
| `0.1.1` | P0a-P0e, P1, P2 | official validate and build pass, catalog install lifecycle green, traceability gate in CI |
| `0.2.0` | P3-P8 | deterministic GitHub adapter plus all backlog, uncertainty, and outcome workflows |
| `0.3.0` | P9-P11 | greenfield/brownfield correctness, monorepo targeting, OpenCode roles |
| `0.9.0` | P12-P13 | every must-level acceptance scenario passes, four pilot streams complete |
| `1.0.0` | P14 | repository public, catalogs published, hosted-catalog install verified |

Milestones carry no due dates. There are none to state, and inventing them would
be the same mistake as filling in Outcome Status.

The two upstream tracking issues are deliberately unmilestoned: their timing
depends on Spec Kit, not on this roadmap.

## Delivery Status leads; closure follows

Delivery Status is the record. Closing an issue is a consequence of reaching
Output Done, never the thing that records it.

That ordering was violated in practice before it was written down here: sixteen
issues were closed while their Delivery Status still read Inbox, Ready, or
Refining. The work was done and the commits prove it, but the field that is
supposed to be authoritative had rotted, and the board would have reported four
completed phases as untriaged.

The rule, in order:

1. Move the item to Output Done.
2. Then close it.
3. An Epic is In Progress while any child is, and Output Done only when its
   children are.

Reconciling closed issues after the fact is a repair, not the process. If the
field is being backfilled, the board was not being used to run the work.

## A gap: nothing represents blocked

`policy/state-machine.yml` defines Inbox, Refining, Ready, In Progress, and
Output Done. None of them describes an item that is understood, agreed, and
waiting on something outside this project.

#28 and #29 are exactly that: fully specified, worked around, and waiting on
Spec Kit's maintainers. They currently sit in Inbox, which reads as untriaged
and is wrong.

This is a real gap in the policy rather than a board problem. Recorded here
rather than patched, because changing the state machine is a governance decision
and belongs in an ADR.

## Closing versus Output Done

An Epic is closed once its Delivery Status reaches Output Done, which
`github-schema.yml` permits via `close_completed_after_output_done: true`.

The inverse never holds. `infer_output_done_from_closed_issue` is false: an
issue closed for any other reason (duplicate, withdrawn, superseded) says
nothing about whether the work was completed. Delivery Status is authoritative;
closure is a consequence of it, never evidence for it.

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

## Epics are the roots

Every issue hangs off a phase Epic. A rootless issue is an exception and needs a
reason, not an omission.

- **Stories** attach to the Epic whose phase they deliver.
- **Spikes** attach to whatever they unblock — the Story if one exists, otherwise
  the Epic. A spike is bounded investigation *for* something, so it inherits that
  something's parent.
- **Upstream trackers** attach to the phase whose exit gate they constrain, not
  the phase that discovered them. #28 and #29 surfaced during P0c but sit under
  P12, because what they block is claiming the lifecycle is fully verified.

Upstream trackers are also deliberately unmilestoned: their timing belongs to
another project's maintainers.

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

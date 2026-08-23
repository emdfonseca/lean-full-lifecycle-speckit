# Development tracking

Roadmap execution is tracked on GitHub rather than in a document, using the
mechanisms this bundle itself prescribes.

| What | Where |
|---|---|
| Repository | https://github.com/emdfonseca/lean-full-lifecycle-speckit (private) |
| Project board | https://github.com/users/emdfonseca/projects/3 |
| Phases | one Epic issue per roadmap phase, `P0a` through `P14` |
| Delivery state | the board's built-in `Status` field, carrying the state machine |
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

## Ready is a gate, not a waypoint

`Refining → In Progress` is not a legal transition. The path is
`Refining → Ready → In Progress`, and the two steps exist separately because
they carry different authorities:

| Transition | Authority | Evidence |
|---|---|---|
| Refining → Ready | product or refinement authority | `readiness_verdict_ready` |
| Ready → In Progress | assigned engineering owner | `owner_assigned`, `work_started` |

Collapsing them exercises both authorities at once. Ready is what makes an item
*eligible* to be started; setting it in the same motion as In Progress means no
readiness verdict was ever produced and nothing was ever gated.

Stories #35 and #36 did exactly that and are recorded as such rather than
backfilled. A project board applies no transition validation, so the illegal
move was silently accepted — which is the argument for the deterministic
transition command rather than an argument against the model.

The sequence:

1. Refine until no blocking questions remain, and write the verdict.
2. Move to Ready. This is a decision, and it is not the same person's to make
   as the one who starts the work.
3. Assign an owner, then move to In Progress.

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

`policy/github-schema.yml` defines project-scoped fields as the default
(ADR 0003). This board runs that default, with `authoritative_project_count: 1`
and `allow_status_labels: false`. Organization Issue Fields are an opt-in for
organizations wanting one vocabulary across many repositories, and they apply
organization-wide, which is a cost rather than an upgrade for a single
repository.

Every field the schema names exists on the board: the delivery state in the
built-in `Status` field, plus Outcome Status, Risk, Severity, Priority, and
Capability as custom fields. The schema is
therefore implementable as written, which was previously untested.

### The delivery state lives in the built-in field

Projects ships a built-in `Status` field with Todo / In Progress / Done. It is
the field board views group by, and GitHub's own workflows write to it.

Carrying the delivery state in a *separate* custom field, as this board first
did, has a failure mode that is invisible until someone looks at the board: the
default view groups by `Status`, GitHub's automation only ever moves items
Todo → Done, and In Progress is therefore never populated. The board reported
twenty items Done and nineteen Todo while the authoritative field recorded five
distinct states.

So the built-in field carries the state machine directly:

```
Status: Inbox | Refining | Ready | In Progress | Output Done
```

One field, natively understood by grouping and views, with no mirror to keep in
sync.

**It cannot be renamed.** `updateProjectV2Field` accepts a new name for the
built-in field, reports success, and silently keeps `Status`. The name therefore
differs from `Delivery Status` as `github-schema.yml` calls it; the values are
what matter, and this is a documented property of the Projects fallback rather
than a discrepancy to reconcile.

**Losing GitHub's auto-Done is deliberate.** Its built-in workflow sets `Done`
when an issue closes. With `Done` gone, that automation no longer fires — which
is what `infer_output_done_from_closed_issue: false` requires. Closure must
never write a completion state.

One further caveat: these are *Project* fields, not Issue Fields. They apply to
items on the board, not to issues repository-wide. Moving to an organization
would change the mechanism, not the model.

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

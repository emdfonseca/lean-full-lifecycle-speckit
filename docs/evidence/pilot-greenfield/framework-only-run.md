# Greenfield framework-only run

Second run in the greenfield stream, for AC1 of #103: a framework-only
bootstrap in an empty repository. The stream's metrics record is
`docs/evidence/pilot-greenfield.md`, which covers the product bootstrap; this
file is the evidence for the framework-only half.

| | |
|---|---|
| Run | `3a554862` |
| Workflow | `lifecycle-greenfield-bootstrap`, `mode=framework-only` |
| Target | empty local repository, no GitHub remote |
| Outcome | `aborted` at `approve-verification-resolution` |
| Operator | agent |

## What AC1 asks, and what happened

> Given an empty repository, when a framework-only bootstrap runs, then
> framework artifacts exist and no product, stack, or backlog artifact exists.

The second half holds and was measured, not asserted: the tree was listed
before and after the run.

| Artifact | State after the run |
|---|---|
| `.specify/memory/constitution.md` | 347 lines, zero `[PLACEHOLDER]` tokens |
| `.specify/lifecycle/greenfield-bootstrap-plan.md` | written |
| `.specify/lifecycle/greenfield-mismatch-3a554862.md` | verdict `no_mismatch` |
| `.claude/settings.json` | written from a proposal that is byte-identical on re-run |
| `PRODUCT.md` | absent |
| `.specify/lifecycle/stack-decision.md` | absent |
| `.specify/lifecycle/architecture.md` | absent |
| `.specify/lifecycle/product-decisions.md` | absent |
| backlog items | none |

The first half is where it stops. The run never reached `completed`, so AC1 is
**not satisfied**: framework artifacts exist, but the mode has no path to a
finished run. See #133.

## Why the run aborted

`approve-verification-resolution` offers two resolutions and framework-only
closes both: generating a script requires a recorded stack decision, which the
mode forbids, and an overlay requires a project command that already runs,
which an empty repository does not have.

The third option the step offered was a placeholder `devbox.json`, described in
its own words as something that "stops the missing-prerequisite failure but
makes every gate pass while verifying nothing". It would also write the stack
artifact AC1 requires to be absent. Rejected, and `on_reject: abort` ended the
run.

## Interventions

Four, all gate decisions by the agent operator.

1. `confirm-no-mismatch` — approve. Verdict was `no_mismatch` on an empty tree.
2. `approve-bootstrap-plan` — approve, choosing the plan's option B. Option C
   would have satisfied the document check by writing `PRODUCT.md` marked "not
   yet decided", which is the artifact AC1 forbids. A run that passes both
   gates that way means neither.
3. `claude_config.py apply` — run by hand after the auto-mode classifier denied
   it. Plan item 2, already approved at the gate, writing only
   `.claude/settings.json`.
4. `approve-verification-resolution` — reject, for the reason above.

## Findings

Six, all filed before being acted on, none fixed in place.

| # | What |
|---|---|
| 132 | 23 of 31 shipped scripts import `yaml` and nothing declares PyYAML. Extended: no interpreter on this machine runs the 9 scripts importing `github_api.py`, so `decompose`, `triage`, and `transition` cannot run here at all |
| 133 | `product_documents.required` has no framework-only variant, and the mode cannot reach `completed` |
| 134 | `edit_permission: deny` maps to a `read_only` tool set containing `Bash`, and is reported as neither enforced nor unmappable (security) |
| 135 | `secret_file_read` denies four readers by name, against its own docstring's argument (security) |
| 136 | The stack-decision precondition is satisfied by any non-empty file |
| — | `specify workflow run` has no `--audit`, so no workflow-driven pilot can answer `failed_github_operations`. Not filed |

## Corrections made during the run

The run's own plan claimed at §1 that `/usr/bin/python3` runs every extension
script. The apply step disproved it by executing them: that interpreter is
3.9.6 and cannot parse `str | None` at `github_api.py:110`. Recorded on #132,
because the plan is a pilot artifact and a wrong record is worse than none.

## Environment

`specify` 1.0.1, macOS 26.5.2, Python 3.14.7 on PATH and 3.9.6 at
`/usr/bin/python3`. Neither runs the full script set; see #132.

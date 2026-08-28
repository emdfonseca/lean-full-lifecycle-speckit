# Measured traceability, against the markers

Two systems now answer "is this requirement verified", and they disagree. This
records the disagreement so `@pytest.mark.req` and the reciprocity check can be
removed on evidence rather than on faith — which is what #171's own risk note
asked for and what this document exists to supply.

Run it with `make measure`. It is not in `make validate`: it runs the whole
suite under coverage, and every source check would pay for that.

## What each system can answer

| | markers + reciprocity | measured coverage |
|---|---|---|
| A cited test exists and claims the requirement back | yes | no |
| A cited test executes the component | no | for executable components |
| Components that are policy, commands, workflows, manifests | named only | nothing |

Neither is a superset of the other, which is why both run.

## The reach, measured rather than assumed

125 requirements. **80 carry at least one component coverage can speak for; 45
carry none at all.** For those 45 the markers remain the only check, and that is
fine — node existence is the half that already works.

`script:` is used for any file the repository owns, not only for code. A
`script:Makefile` or `script:README.md` is unmeasurable, not failing; reporting
a Makefile as "cited and not executed" would be the measurement crying wolf.

## The disagreement, at the time of writing

Every requirement below passes the marker system and fails the measurement:
its cited tests never execute the component it names.

| Requirement | Component | What the run saw |
|---|---|---|
| REQ-PACKAGE-CATALOG-001 | `script:scripts/local_catalog.py` | 11 other tests ran it |
| REQ-PACKAGE-CATALOG-001 | `script:scripts/generate_catalogs.py` | 1 other test ran it |
| REQ-PACKAGE-LIFECYCLE-001 | `script:scripts/smoke_test.py` | nothing ran it |
| REQ-PACKAGE-ARTIFACT-001 | `script:scripts/build_release.py` | nothing ran it |
| REQ-TOOLING-SOT-001 | `script:scripts/lib/inventory.py` | 131 other tests ran it |
| REQ-TOOLING-SOT-001 | `script:scripts/generate_manifests.py` | 1 other test ran it |
| REQ-TOOLING-SOT-001 | `script:scripts/generate_catalogs.py` | 1 other test ran it |
| REQ-BACKLOG-AC-001 | `script:scripts/generate_item_templates.py` | 1 other test ran it |
| REQ-BACKLOG-REFINE-001 | `check:INV-GATE-SHAPE` | 24 other tests ran it |
| REQ-PILOT-EVIDENCE-001 | `script:tooling/pilots/pilot_record.py` | nothing ran it |
| REQ-PACKAGE-INTERPRETER-001 | `script:.../github_api.py` | 245 other tests ran it |
| REQ-PACKAGE-GIT-001 | `script:.../transition_plan.py` | 131 other tests ran it |
| REQ-CORE-INTEGRATION-001 | `check:INV-INTEGRATION-DEFAULT` | 24 other tests ran it |
| REQ-CORE-FLAVOUR-001 | `check:INV-SCRIPT-FLAVOUR` | 24 other tests ran it |

Two shapes, and they need different answers.

**Nothing ran it** — `smoke_test.py`, `build_release.py`, `pilot_record.py`.
The component is genuinely unexercised by the suite. Either a test should
exercise it or the requirement names the wrong component.

**Others ran it, the cited ones did not** — the rest. The component is well
exercised; the requirement cites tests about something adjacent. Usually the
`components` list is too broad: `REQ-PACKAGE-INTERPRETER-001` is about what an
extension manifest declares, and names `github_api.py` because that is code the
declaration affects.

None is fixed here. Deciding whether the component or the citation is wrong is
a judgement per requirement, and doing fourteen of them inside the story that
built the measurement would bury the measurement in them.

## Removing the markers

Not yet, and not on this document alone. #171 asks for a release of the two
running alongside before anything comes out. What that release needs to show:
the fourteen above resolved or explained, and no case where the markers caught
something the measurement missed on a requirement the measurement can speak for.

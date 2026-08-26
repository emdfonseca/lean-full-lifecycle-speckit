stream: brownfield
owner: emdfonseca
target: a dissociated clone of a real Chrome extension, 445 commits, pnpm workspace
started: 2026-08-25
finished: 2026-08-25

# Recorded by the agent that drove the run. developer_satisfaction is left for
# a person: it is a judgement about the experience of doing the work, and an
# agent reporting one would be inventing a reading nobody had.
#
# This covers the no-target scan half of #104: AC1 and AC5. AC2, AC3, AC4 and
# AC6 need targeted runs and have not happened, so this record is deliberately
# partial and the stream is not complete. Run report:
# docs/evidence/pilot-brownfield/lunma-scan-run.md
#
# An earlier scan against `records` produced the artifacts already in
# docs/evidence/pilot-brownfield/. It is a separate target and is not counted
# here; mixing two targets in one stream's metrics would report a coverage
# neither earned.

metrics:
  workflow_completion_without_repair:
    verdict: breached
    evidence: >-
      The run reached completed, but its own validation step reports the
      verification resolution as an unresolved blocker, and the discovery
      record could not be certified because sensitive.py crashed on it. Neither
      was repaired in place; both are filed as #144 and #143.
    recorded_by: agent
  human_interventions:
    verdict: observed
    evidence: >-
      Three gate decisions -- adoption plan, discovery, verification resolution
      -- plus one scan I ran by hand, applying the policy patterns to the
      discovery record because sensitive.py could not. That fourth one is an
      intervention rather than a step: without it the discovery gate would have
      been approved on an uncertified record.
    recorded_by: agent
  incorrect_or_out_of_scope_edits:
    verdict: held
    evidence: >-
      Measured by diff against a tree committed clean before adoption started.
      One tracked file changed, `.specify/memory/constitution.md`. Every build
      path is byte-identical: devbox.json, pnpm-workspace.yaml, every
      package.json, pnpm-lock.yaml, biome.json, .github/, .githooks/, apps/,
      packages/. No product code was touched.
    recorded_by: agent
  readiness_accuracy:
    verdict: not_applicable
    evidence: >-
      No readiness verdict was produced. Adoption stops before any item reaches
      Refining, and no backlog item was created: the clone is dissociated, so
      no GitHub target exists to create one on.
    recorded_by: agent
  duplicate_backlog_rate:
    verdict: not_applicable
    evidence: >-
      No backlog item was created. AC6, duplicate triage at the gate, needs a
      GitHub target and a targeted run; neither happened here.
  convergence_findings:
    verdict: not_applicable
    evidence: No converge step runs in adoption, and no promoted work exists yet.
  ready_to_output_done_hours:
    verdict: not_applicable
    evidence: No item was delivered.
  failed_github_operations:
    verdict: not_applicable
    evidence: >-
      No GitHub operation was attempted. inspect-github refused for want of a
      target and wrote nothing, which is the intended refusal rather than a
      failure: the clone has no remote by design.
  model_cost:
    verdict: unmeasured
    evidence: Not instrumented in this run.
  model_runtime_minutes:
    verdict: unmeasured
    evidence: >-
      Not recorded per step. No step approached its timeout; the longest were
      the document-writing steps at the artifact_synthesis tier.
  test_flakiness:
    verdict: not_applicable
    evidence: >-
      The target's suite was never run. `pnpm verify` needs node_modules, the
      plan's approval to run `pnpm install` had no gate and no key in
      inputs.json so it was never asked, and the report says so rather than
      claiming a pass.
  developer_satisfaction:
    verdict: unrecorded
    evidence: Needs a person. Not recorded by the agent that drove the run.
  generated_artifacts_disposed:
    verdict: observed
    evidence: >-
      The clone is retained until this record is reviewed. It is dissociated
      from its origin and has no remotes, so disposal is a directory delete
      with nothing to detach first.
    recorded_by: agent

failures:
  - what: >-
      The decision-record directory is hardcoded to docs/decisions/ in prose
      and never discovered. The target keeps five Nygard ADRs in docs/adr/,
      which the contract cannot see.
    tracked_by: 141
  - what: >-
      A ratchet baseline records no scope, so widening what is measured reads
      as a regression and narrowing it ratchets the baseline up automatically.
      The target scopes coverage to one directory.
    tracked_by: 142
  - what: >-
      sensitive.py --record parses YAML before scanning, so it crashes on the
      Markdown discovery records its own documentation points at. The evidence
      gate was reached with the record uncertified.
    tracked_by: 143
  - what: >-
      Approving the verification resolution performs nothing. No step consumes
      the gate's verdict, so the overlay is never written and the run reports
      completed with the blocker outstanding.
    tracked_by: 144
  - what: >-
      establish-constitution writes a constitution that fails the document
      contract on 13 counts, three of which stated no RFC 2119 keyword at all.
      A validator promoted three of the project's stated intentions from
      opinions to obligations.
    tracked_by: 145

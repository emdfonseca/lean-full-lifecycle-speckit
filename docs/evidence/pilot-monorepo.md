stream: monorepo
owner: emdfonseca
target: a two-member Spec Kit monorepo and a git worktree of it, built for this run
started: 2026-08-25
finished: 2026-08-25

# Recorded by the agent that drove the runs.
#
# This stream verifies resolution rather than delivery. No workflow was run and
# no item was transitioned in the pilot project, so the metrics that measure a
# delivery loop are not_applicable rather than zero. Run report:
# docs/evidence/pilot-monorepo/run.md

metrics:
  workflow_completion_without_repair:
    verdict: held
    evidence: >-
      No repair was needed. Every command behaved as its contract states on
      first run, in both members, in a nested directory, and in a worktree.
      This is the first pilot stream this session to find no defect.
    recorded_by: agent
  human_interventions:
    verdict: observed
    evidence: >-
      None. No gate was reached, because this stream exercises resolution and
      containment rather than a workflow. Zero recorded deliberately rather
      than left unmeasured.
    recorded_by: agent
  incorrect_or_out_of_scope_edits:
    verdict: held
    evidence: >-
      Nothing outside the pilot project was written. Three escape attempts from
      the worktree were refused by OutsideProjectError and no file appeared at
      any of the three targets, which was checked rather than assumed.
    recorded_by: agent
  readiness_accuracy:
    verdict: not_applicable
    evidence: >-
      No readiness verdict was produced in the pilot project. Nothing reached
      Refining, so there is no verdict to be right or wrong about.
    recorded_by: agent
  duplicate_backlog_rate:
    verdict: not_applicable
    evidence: No backlog item was created in the pilot project.
  convergence_findings:
    verdict: not_applicable
    evidence: No converge step runs in this stream; no spec exists to diverge from.
  ready_to_output_done_hours:
    verdict: not_applicable
    evidence: No item was delivered in the pilot project.
  failed_github_operations:
    verdict: held
    evidence: >-
      Two commands reached GitHub, both plan generations against
      emdfonseca/lean-full-lifecycle-speckit, and both returned. No --audit file
      was written, because the flag exists on the extension's scripts and the
      calls here were direct rather than through a workflow.
  model_cost:
    verdict: unmeasured
    evidence: Not instrumented in this run.
  model_runtime_minutes:
    verdict: unmeasured
    evidence: >-
      Not recorded per command. Every command in this stream returned in under
      a second; nothing here approaches the step timeouts that #116 and #117
      were about.
  test_flakiness:
    verdict: observed
    evidence: >-
      The repository suite ran 1199 tests green during this stream. No test in
      the pilot project: none exists.
    recorded_by: agent
  generated_artifacts_disposed:
    verdict: observed
    evidence: >-
      The pilot monorepo and its worktree are retained until this record is
      reviewed. The worktree is registered with git and needs
      `git worktree remove` rather than a directory delete, which is named here
      so disposal does not leave a stale registration behind.
    recorded_by: agent

# No failure was found, so this list is empty and that is a claim rather than
# an omission: five acceptance criteria were exercised and each held. The two
# near-misses below were errors in how I measured, not in what was measured,
# and both are recorded in the run report rather than as defects.
failures: []

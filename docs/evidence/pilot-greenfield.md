stream: greenfield
owner: emdfonseca
target: plaincodelab/pilot-greenfield
started: 2026-08-24
finished: 2026-08-24

# Recorded by the agent that drove the run. developer_satisfaction is left for
# a person: it is a judgement about the experience of doing the work, and an
# agent reporting one would be inventing a reading nobody had.

metrics:
  workflow_completion_without_repair:
    verdict: breached
    evidence: >-
      Three runs were needed. Two failed on step timeouts (#116, #117) and one
      was rejected at the plan gate for an empty product context. The fourth
      completed end to end.
    recorded_by: agent
  human_interventions:
    verdict: observed
    evidence: >-
      Four gate decisions (mismatch approve, plan reject, plan approve, product
      approve, verification approve counted as four distinct approvals plus one
      reject), one target reconfiguration, and two bundle fixes mid-pilot.
    recorded_by: agent
  incorrect_or_out_of_scope_edits:
    verdict: held
    evidence: >-
      Diff reviewed against the approved register. Everything written was named
      in the plan; the six AR items the plan refused stayed unwritten.
    recorded_by: agent
  readiness_accuracy:
    verdict: not_applicable
    evidence: >-
      Not measurable in this run. Bootstrap stops before any item reaches
      Ready, and all nine created items are at Inbox, so no readiness verdict
      was produced to be right or wrong about.
    recorded_by: agent
  duplicate_backlog_rate:
    verdict: observed
    evidence: Nine items created, none refused as a duplicate.
    recorded_by: agent
  convergence_findings:
    verdict: not_applicable
    evidence: No converge step runs in the bootstrap workflow.
  ready_to_output_done_hours:
    verdict: not_applicable
    evidence: >-
      No item reached Output Done. Bootstrap deliberately stops at startable
      work, which AC-GREENFIELD-007 asserts.
  failed_github_operations:
    verdict: unmeasured
    evidence: >-
      No --audit file was written for the workflow's own calls, but every
      GitHub write in the run was read back by the command that made it and
      none disagreed.
  model_cost:
    verdict: unmeasured
    evidence: Not instrumented in this run.
  model_runtime_minutes:
    verdict: unmeasured
    evidence: >-
      Not recorded per step. The apply step alone exceeded ten minutes, which
      is what #116 and #117 were about.
  test_flakiness:
    verdict: not_applicable
    evidence: No project test suite exists yet; the stack decision is undecided.
    recorded_by: agent
  developer_satisfaction:
    verdict: unrecorded
    evidence: Needs a person. Not recorded by the agent that drove the run.
  generated_artifacts_disposed:
    verdict: observed
    evidence: >-
      The pilot project is retained until the record is reviewed. One artifact
      the run could not clean up is named in the report: /tmp/specdiag-venv,
      outside the allowed directories, needs a manual removal.
    recorded_by: agent

# A second run in this stream, framework-only for AC1, is recorded in
# docs/evidence/pilot-greenfield/framework-only-run.md. It aborted at the
# verification gate; the metrics above describe the product bootstrap only.

failures:
  - what: >-
      Command docs prescribed a bare `python <script>` invocation. Failed three
      ways on one machine, and two agents invented two different workarounds in
      the same run.
    tracked_by: 114
  - what: >-
      model-routing.yml named an opencode-only inventory command for every
      integration, so under claude its one executable instruction could not run.
    tracked_by: 115
  - what: >-
      No workflow step declared a timeout. create-bootstrap-plan exceeded the
      300s default as soon as the product context was real; it had passed with
      an empty one.
    tracked_by: 116
  - what: >-
      The timeout fix classified steps by id prefix. apply-greenfield-bootstrap
      matched no rule and timed out two steps later, in the same workflow.
    tracked_by: 117
  - what: >-
      Four declared field roles cannot exist on the organization Issue Fields
      backend, so Outcome Status transitions and security-finding Severity have
      no field to write to.
    tracked_by: 118
  - what: >-
      Nothing creates the Projects v2 board the default deployment shape needs,
      and the bootstrap does not say one is required.
    tracked_by: 119
  - what: >-
      23 of 31 shipped scripts import yaml and nothing declares PyYAML. No
      interpreter on this machine runs the 9 importing github_api.py, so
      decompose, triage, and transition cannot run at all.
    tracked_by: 132
  - what: >-
      product_documents.required has no framework-only variant, and the mode
      has no path to a completed run.
    tracked_by: 133
  - what: >-
      edit_permission deny maps to a read_only tool set containing Bash, and is
      reported as neither enforced nor unmappable.
    tracked_by: 134
  - what: >-
      secret_file_read denies four readers by name, which its own docstring
      argues is not a boundary.
    tracked_by: 135
  - what: >-
      The stack-decision precondition is satisfied by any non-empty file, so
      the guard against inventing a toolchain clears on every bootstrap.
    tracked_by: 136

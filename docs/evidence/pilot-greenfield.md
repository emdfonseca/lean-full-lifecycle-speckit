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
    value: false
    why: >-
      Three runs were needed. Two failed on step timeouts (#116, #117) and one
      was rejected at the plan gate for an empty product context. The fourth
      completed end to end.
    recorded_by: agent
  human_interventions:
    value: 7
    why: >-
      Four gate decisions (mismatch approve, plan reject, plan approve, product
      approve, verification approve counted as four distinct approvals plus one
      reject), one target reconfiguration, and two bundle fixes mid-pilot.
    recorded_by: agent
  incorrect_or_out_of_scope_edits:
    value: 0
    why: >-
      Diff reviewed against the approved register. Everything written was named
      in the plan; the six AR items the plan refused stayed unwritten.
    recorded_by: agent
  readiness_accuracy:
    value: not_applicable
    why: >-
      Not measurable in this run. Bootstrap stops before any item reaches
      Ready, and all nine created items are at Inbox, so no readiness verdict
      was produced to be right or wrong about.
    recorded_by: agent
  duplicate_backlog_rate:
    value: 0
    why: Nine items created, none refused as a duplicate.
    recorded_by: agent
  convergence_findings:
    value: null
    why: No converge step runs in the bootstrap workflow.
  ready_to_output_done_hours:
    value: null
    why: >-
      No item reached Output Done. Bootstrap deliberately stops at startable
      work, which AC-GREENFIELD-007 asserts.
  failed_github_operations:
    value: 0
    why: >-
      No --audit file was written for the workflow's own calls, but every
      GitHub write in the run was read back by the command that made it and
      none disagreed.
  model_cost:
    value: null
    why: Not instrumented in this run.
  model_runtime_minutes:
    value: null
    why: >-
      Not recorded per step. The apply step alone exceeded ten minutes, which
      is what #116 and #117 were about.
  test_flakiness:
    value: 0
    why: No project test suite exists yet; the stack decision is undecided.
    recorded_by: agent
  developer_satisfaction:
    value: null
    why: Needs a person. Not recorded by the agent that drove the run.
  generated_artifacts_disposed:
    value: 0.0
    why: >-
      The pilot project is retained until the record is reviewed. One artifact
      the run could not clean up is named in the report: /tmp/specdiag-venv,
      outside the allowed directories, needs a manual removal.
    recorded_by: agent

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

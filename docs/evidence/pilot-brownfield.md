stream: brownfield
owner: emdfonseca
target: a dissociated clone of a real Chrome extension, 450 commits, pnpm workspace
started: 2026-08-25
finished: 2026-08-26

# Recorded by the agent that drove the runs.
#
# Three runs against one target, covering AC1 through AC7:
#   af600cc4  scan       no target        AC1, AC5
#   be6df5ff  targeted   a bug            AC2, AC4, AC5, AC7
#   3242c6bc  targeted   a feature        AC3, AC5
# AC6 ran outside the workflow, against plaincodelab/pilot-brownfield, because
# it is board behaviour and needs no codebase. Run reports:
# docs/evidence/pilot-brownfield/lunma-scan-run.md
#
# AC2's defect was staged, not found. The predicate fixed by commit 02d5456 was
# reverted deliberately so a real failing regression test existed to start from.
# Stated here because a record that let it read as a wild find would be lying
# about the strongest evidence in the stream: the framework identified it as a
# deliberate revert from git history, unprompted.
#
# An earlier scan against `records` produced the artifacts already in
# docs/evidence/pilot-brownfield/. It is a separate target and is not counted
# here; mixing two targets in one stream's metrics would report a coverage
# neither earned.

metrics:
  workflow_completion_without_repair:
    verdict: breached
    evidence: >-
      Three runs, none clean. af600cc4 reported the verification resolution as
      an unresolved blocker and could not certify its own discovery record.
      be6df5ff reached the apply step and lost five minutes of work to a
      timeout budgeted at the wrong tier. 3242c6bc completed but its
      verification report recommended an overlay that no code path reads. Each
      failure was filed rather than repaired in place.
    recorded_by: agent
  human_interventions:
    verdict: observed
    evidence: >-
      Nine gate decisions across the three runs, plus one framework fix that
      had to land before a targeted run could start at all (#148, the apply
      step budgeted at the statement tier), plus rebuilding the target clone
      because the previous one was thrown away, plus scrubbing the upstream
      repository identity from the clone after #158.
    recorded_by: agent
  incorrect_or_out_of_scope_edits:
    verdict: held
    evidence: >-
      Measured after each targeted run as
      `git diff --name-only -- . ':(exclude).specify'`, which returned zero
      files both times. devbox.json, package.json, pnpm-lock.yaml,
      pnpm-workspace.yaml and .github/ were byte-identical, checked by hash
      across gate 3 of run 3242c6bc specifically because that gate proposed
      writing to devbox.json and the proposal was refused.
    recorded_by: agent
  readiness_accuracy:
    verdict: not_applicable
    evidence: >-
      No item reached Ready. Adoption stops at a readiness verdict about the
      target and never transitions a backlog item, so there is nothing to have
      been right or wrong about.
    recorded_by: agent
  duplicate_backlog_rate:
    verdict: held
    evidence: >-
      AC6, run against plaincodelab/pilot-brownfield. Two near-duplicates
      existed (#1, #2). capture reported both with scores 1.0 and 0.857 and
      refused creation with exit 1. Naming one of the two still refused, naming
      the one outstanding. Naming both created issue #3. The refusal names the
      wrong way out and closes it: "Raising --threshold hides the report
      instead of answering it."
    recorded_by: agent
  convergence_findings:
    verdict: not_applicable
    evidence: No converge step runs in adoption, and no promoted work exists yet.
    recorded_by: agent
  ready_to_output_done_hours:
    verdict: not_applicable
    evidence: No item was delivered. Adoption adopts; delivery is a separate workflow.
    recorded_by: agent
  failed_github_operations:
    verdict: breached
    evidence: >-
      Not a failed call — a call that should never have been made. inspect
      recovered the upstream repository lunma-app/lunma from SECURITY.md,
      .github/CODEOWNERS, apps/extension/CHANGELOG.md and
      apps/site/src/lib/links.ts, then queried GitHub with live credentials,
      despite the clone having no remote and the extension config carrying
      organization and repository null. Read-only, and #120's fix correctly
      refused to offer the owner's unrelated board. Filed as #158; the clone's
      content was scrubbed before the AC3 run.
    recorded_by: agent
  model_cost:
    verdict: unmeasured
    evidence: No instrument exists. Nothing in the runner or the extension records cost.
    recorded_by: agent
  model_runtime_minutes:
    verdict: unmeasured
    evidence: >-
      Wall clock is available and per-step time is not. Run be6df5ff took 113
      minutes across 13 steps; state.json's step_results carry no timestamps,
      so no step can be attributed. That is why this entry has never been
      answerable in any stream.
    recorded_by: agent
  test_flakiness:
    verdict: held
    evidence: >-
      The target's suite ran four times across the stream — 3191 tests in 172
      files, plus 23 in the site package. Identical results every run; no test
      passed and failed on the same code. First stream able to answer this at
      all: pnpm install --frozen-lockfile completes in 5.6s, which the scan run
      never established.
    recorded_by: agent
  generated_artifacts_disposed:
    verdict: observed
    evidence: >-
      Nothing disposed yet. The clone at ~/Workspaces/_pilot-brownfield-lunma
      and the throwaway repo plaincodelab/pilot-brownfield are both retained
      until this record is reviewed. The clone is dissociated and scrubbed, so
      retaining it leaks nothing; deleting it loses the ability to re-measure
      any figure above.
    recorded_by: agent

failures:
  - what: >-
      The decision-record directory is hardcoded to docs/decisions/ in prose
      and never discovered. The target keeps five Nygard ADRs in docs/adr/,
      which the contract cannot see. Reproduced again in run 3242c6bc.
    tracked_by: 141
  - what: >-
      A ratchet baseline records no scope, so widening what is measured reads
      as a regression and narrowing it ratchets the baseline up automatically.
      The target scopes coverage to one directory.
    tracked_by: 142
  - what: >-
      sensitive.py --record parses YAML before scanning, so it crashes on the
      Markdown discovery records its own documentation points at. The evidence
      gate was reached with the record uncertified. Fixed during this stream;
      runs be6df5ff and 3242c6bc scanned their records line-anchored.
    tracked_by: 143
  - what: >-
      Approving the verification resolution performs nothing. No step consumes
      the gate's verdict, so the overlay is never written and the run reports
      completed with the blocker outstanding. Confirmed live in be6df5ff with a
      recorded approval behind it. Run 3242c6bc found the other half: the
      overlay is inert anyway, because ShellStep.execute runs config["run"]
      verbatim and reads no overlay, so writing one would flip the check to
      resolved while every devbox run verify step still failed.
    tracked_by: 144
  - what: >-
      establish-constitution writes a constitution that fails the document
      contract on 13 counts, three of which stated no RFC 2119 keyword at all.
      A validator promoted three of the project's stated intentions from
      opinions to obligations.
    tracked_by: 145
  - what: >-
      targeted-apply-approved-scope was budgeted at the statement tier, 300s,
      and timed out applying a change to a real repository. It blocked every
      targeted run, so it was fixed before this stream could continue. Testing
      the same property across all fourteen workflows found four under-budgeted
      steps, not the one reported.
    tracked_by: 148
  - what: >-
      An approval gate's artifact does not say what is being decided. The
      approver could not locate the single judgement call in a 196-line plan,
      and in the AC3 run could not find seven blocking questions referenced as
      Q1-Q7 but defined in an unheaded numbered list.
    tracked_by: 155
  - what: >-
      The bundle hardcodes devbox as the only verification command runner, in
      five workflow run: steps and the verification policy, and declares it
      nowhere. A healthy pnpm project that uses devbox only to provision a
      toolchain was reported as missing verification.
    tracked_by: 156
  - what: >-
      git is executed by transition_plan.py and declared in no requires.tools
      block, while gh, python3 and PyYAML are declared.
    tracked_by: 157
  - what: >-
      inspect infers the target repository from file content when no remote is
      configured, defeating remote-removal as a dissociation method and
      querying GitHub with live credentials against a repository the working
      tree has no configured relationship to.
    tracked_by: 158

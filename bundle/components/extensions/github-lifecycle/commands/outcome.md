---
description: Workflows, not people — assess an outcome record and recommend a status.
scripts:
  py: scripts/outcome.py
---

# GitHub Lifecycle Outcome

Decide what a measurement means, and refuse to conclude more than it supports.

```bash
{SCRIPT} \
  --record .specify/lifecycle/outcome/<id>.md
```

## What it will conclude, and what it will not

**A regressed guardrail defeats a met target.** Guardrails name the harm a
success is not permitted to cause, so a success that caused it is not one.
Report both facts: the target was met, and it does not change the assessment.

**Insufficient evidence is not failure.** An unelapsed window or a sample below
its stated minimum leaves the item Measuring. Recording it as missed invents a
result the data does not support, and a team that has been told its work failed
on thin evidence will not measure honestly next time.

**An unreadable data source blocks.** Absent data is not evidence of absence.

## Recommend, never decide

`outcome-policy.yml` names `product_owner` and `analytics_owner` as the only
validating authorities. This command summarises the evidence, identifies
data-quality gaps, and recommends. Say so in your report rather than leaving a
reader to infer it.

Recording Outcome Validated without a named authority is refused.

## Missed and inconclusive are different findings

The board carries one option for both -- the field is named `Outcome Missed /
Inconclusive` -- so the `finding` in the output and the sentence you write are
what preserve the difference.

**not_met**: the target was not reached and the data says so. A result somebody
can act on.

**inconclusive**: the window elapsed, the sample was large enough, and the
measurement still does not distinguish success from failure. The question is
open. The next step is a better measurement, not a post-mortem.

Reporting the second as the first tells a team its work failed on evidence that
says no such thing. That is the same mistake as calling insufficient evidence a
failure, in the one case the policy did not originally enumerate.

`result` is enumerated: `met`, `not_met`, `inconclusive`. Anything else is
refused rather than guessed at, because free text here is how an open question
became a verdict.

## Never

- Change Delivery Status. Work that was finished stays finished whatever the
  measurement says, and conflating the two makes teams reluctant to measure.
- Recommend a status when the evidence is blocked.
- Narrow a guardrail, extend a window, or lower a minimum sample to reach a
  conclusion. Each is the assessment deciding its own inputs.

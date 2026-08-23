# Outcome Review

Close the loop between work being finished and the result being known.

Delivery and outcome are separate questions. Delivery asks whether the work met
the standard; outcome asks whether it did what it was for. This workflow answers
only the second, and says so at the start and again in the report.

## Why it will not touch Delivery Status

Work that reached Output Done stays there whatever the measurement says. A team
whose finished work is reopened because a metric moved the wrong way learns to
choose safe metrics, and the measurement stops being worth taking. Every plan
step here states that no Delivery Status change is planned.

## The three routes

`speckit.github-lifecycle.outcome` assesses the record and recommends. The
switch routes on that recommendation:

- **measuring** — the window has not elapsed or the sample is too small. The run
  names the date or the number that would settle it. Insufficient evidence is
  not failure.
- **validated** — target met, guardrails intact. The gate requires a product
  owner or analytics owner. This is the one status an agent may never write on
  its own judgement.
- **missed** — including a met target whose guardrail regressed. The run
  searches for an existing finding before proposing a new one.

## Inputs

| Input | Meaning |
|---|---|
| `issue_ref` | the item under review |
| `record_path` | the outcome record to assess |
| `assessed_status` | set from the assessment, not from what was hoped |
| `outcome_verdict` | the human decision at the status gate |
| `finding_verdict` | whether a follow-up finding is created |

## Never

- Renegotiate a target, guardrail, or window to change the result.
- Create a follow-up finding without searching first.
- Report a recommendation as a decision.

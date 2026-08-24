---
description: Score a change's risk from policy and name the controls it requires.
scripts:
  py: scripts/risk.py
---

# GitHub Lifecycle Risk

`risk-policy.yml` scores twelve dimensions and names seven overrides. This is
what reads it. A policy nothing reads is a document: it looks like a control,
survives review as a control, and refuses nothing.

Run:

```bash
{SCRIPT} \
  --rating <dimension>=<0-3> ... \
  --override <name> ... \
  --format json
```

Or pass a YAML mapping with `--ratings <path>` instead of repeating `--rating`.

## Report

State the band, the total against the maximum, and every control the band
requires.

**Say which decided it.** An override makes an item high regardless of the
arithmetic, and a reader who cannot tell an overridden high from a scored one
cannot tell what would change it. `overridden` is in the report for that
reason.

**Report the problems.** Three are refusals to act on the score as it stands:
a dimension the policy does not declare scored nothing while looking as though
it scored something; an override it does not declare escalated nothing; an
unrated dimension counted as zero, so the total understates the risk. Rate
them or state why they do not apply.

## The controls are required, not satisfied

`high` requires `authorized_security_review`, and nothing here can decide one
happened. This command names what is required and what is unmet. Reporting a
control as satisfied because it appeared in a list is the failure the command
exists to prevent — `controls_are_required_not_satisfied` is in every report so
a reader never has to infer it.

## Never

- Invent a rating to reach a band. The rating is an assessment; choosing one
  for its result falsifies the assessment.
- Treat an override as a suggestion. Any declared override is high outright:
  the dimensions describe degree, the overrides describe kind.
- Score an item with unrated dimensions and report the total as its risk. Say
  what was not rated.
- Claim a control was performed. Name it as required and let the person who
  performed it say so.

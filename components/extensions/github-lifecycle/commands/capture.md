---
description: Deduplicate and capture an approved lifecycle finding.
---

# GitHub Lifecycle Capture

Capture a finding from `$ARGUMENTS` without expanding active scope.

Required provenance:

- source issue/feature;
- lifecycle phase;
- concrete evidence;
- why it is outside current Acceptance Criteria;
- suggested type/capability/risk/priority;
- related Epic when known.

Before creation:

1. search open and recently closed issues;
2. link a strong duplicate instead of creating;
3. flag a probable duplicate for review;
4. create only a materially distinct approved finding;
5. leave weak/speculative observations in discovery notes.

New findings start with `Delivery Status = Inbox`.

Use native Issue Type and relationships where available. Resolve unique
field/option IDs and read all written values back.

Do not autonomously set roadmap commitment, P0/P1, or Ready status.

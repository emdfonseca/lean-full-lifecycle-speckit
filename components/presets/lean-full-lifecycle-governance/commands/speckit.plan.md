## Lean Full-Lifecycle planning addendum

The plan MUST pass the Constitution Check and include only applicable controls.

Conditionally address:

- architecture boundaries and consequential ADRs;
- security/privacy/trust-boundary changes and abuse cases;
- data/schema migration, compatibility, rollback, and recovery;
- concurrency/idempotency;
- external contract/versioning impact;
- reliability/resilience;
- logs, metrics, traces, audit events, alerts, and runbooks;
- deployment, feature flags, progressive rollout, and rollback;
- test strategy by risk;
- brownfield characterization seams and explicit legacy exceptions;
- artifact authority, ownership, and retention.

Prefer the smallest safe design. Do not introduce layers or extension points for
hypothetical future requirements.
> Apply the canonical installed policy under `.specify/presets/lean-full-lifecycle-governance/policy/` when present.


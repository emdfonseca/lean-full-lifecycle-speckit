## Lean Full-Lifecycle checklist addendum

Generate only checks justified by the change's Acceptance Criteria, risk,
architecture, deployment, and product surface.

Conditionally cover:

- requirements ambiguity and edge cases;
- security/privacy/trust boundaries;
- data migration, compatibility, rollback, and recovery;
- reliability, concurrency, and idempotency;
- logs, metrics, traces, audit events, alerts, and runbooks;
- accessibility and critical user journeys;
- feature flags, rollout, rollback, and flag removal;
- brownfield characterization and quality-ratchet evidence;
- Definition of Output Done evidence.

Do not create a generic ceremonial checklist or duplicate automated gates.

> Apply the canonical installed policy under `.specify/presets/lean-full-lifecycle-governance/policy/` when present.

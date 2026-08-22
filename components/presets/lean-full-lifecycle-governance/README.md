# Lean Full-Lifecycle Governance preset

This preset is deliberately **additive**. It is intended to compose above the
official Lean preset rather than replace Lean's concise commands.

It adds:

- Engineering Excellence;
- Readiness Criteria;
- item Acceptance Criteria vs optional Outcome Criteria;
- Definition of Output Done and Definition of Outcome Done;
- risk-proportionate SSDLC;
- Red–Green–Refactor task ordering;
- brownfield evidence-vs-intent and quality-ratchet rules;
- migration, release, operability, and artifact-lifecycle guidance.

Install for development:

```bash
specify preset add --dev /path/to/lean-full-lifecycle-governance --priority 10
```

Inspect composition:

```bash
specify preset resolve speckit.specify
specify preset resolve speckit.plan
specify preset resolve speckit.tasks
```

The preset also appends risk-shaped guidance to `speckit.checklist`.

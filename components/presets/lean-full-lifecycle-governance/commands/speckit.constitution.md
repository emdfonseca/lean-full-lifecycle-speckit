## Lean Full-Lifecycle governance addendum

When creating or updating the Constitution, encode actionable project-wide
rules for:

1. one authoritative source per mutable fact;
2. progressive formalization and minimum justified ceremony;
3. living specifications and no silent spec/code divergence;
4. Red–Green–Refactor for behavioral production changes where practical;
5. behavior-focused deterministic tests and risk-shaped test depth;
6. simplicity, YAGNI, cohesion, explicit boundaries, and no premature
   abstraction;
7. secure defaults, least privilege, trust-boundary validation, secret safety,
   and risk-triggered threat analysis;
8. reliability, explicit failure handling, idempotency/concurrency semantics,
   and production observability where applicable;
9. small reviewable changes, short-lived branches/worktrees, and frequent
   integration;
10. Devbox-backed reproducibility and no undocumented global dependencies;
11. Definition of Output Done;
12. Definition of Outcome Done and asynchronous outcome validation;
13. identical quality standards for human- and agent-generated code;
14. brownfield quality ratchets and narrow, owned, expiring exceptions.

Rules MUST be specific enough to review or automate. Avoid vague statements
such as “write clean code” or dogma such as 100% coverage, arbitrary function
lengths, abstractions for every duplication, or mandatory E2E tests.
> Apply the canonical installed policy under `.specify/presets/lean-full-lifecycle-governance/policy/` when present.


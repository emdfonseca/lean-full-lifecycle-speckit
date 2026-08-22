## Lean Full-Lifecycle analysis addendum

Also detect:

- Acceptance Criteria without verification evidence;
- engineering requirements copied into product specs;
- tracker metadata duplicated into specs;
- plan/tasks that violate the Constitution or risk policy;
- missing TDD ordering for behavioral changes;
- unsafe parallel tasks with file/schema/dependency overlap;
- high-risk work lacking security/rollback/observability controls;
- brownfield behavior treated as intent without reconciliation;
- Outcome Criteria without an owner or feasible measurement path;
- generated artifacts with no authority/retention policy.

Report findings by severity and identify the authoritative artifact that should
be corrected.
> Apply the canonical installed policy under `.specify/presets/lean-full-lifecycle-governance/policy/` when present.


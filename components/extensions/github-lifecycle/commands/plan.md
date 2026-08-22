---
description: Plan GitHub lifecycle changes without applying them.
---

# GitHub Lifecycle Plan

First run or reuse the current inspection.

Create a plan for the requested operation in `$ARGUMENTS`.

The plan MUST include:

- repository/organization scope;
- current and desired state;
- exact field/option IDs when discoverable;
- required permissions;
- repository-level versus organization-level scope;
- mutation steps;
- read-back verification;
- rollback/recovery;
- risk;
- approval authority.

Organization-level Issue Field or Issue Type changes are always approval
required.

Do not mutate GitHub.

Write the plan under:

```text
.specify/github-lifecycle/plans/<descriptive-id>.md
```

End with exactly one of:

```text
PLAN STATUS: READY FOR APPROVAL
PLAN STATUS: BLOCKED
PLAN STATUS: NO CHANGE
```

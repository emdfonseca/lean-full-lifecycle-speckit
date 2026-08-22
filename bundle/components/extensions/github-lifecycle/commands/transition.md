---
description: Apply one approved GitHub lifecycle field transition.
---

# GitHub Lifecycle Transition

Apply exactly one approved issue-field transition.

Required context:

```text
issue
field
target value
reason
approved plan path
```

Before mutation:

1. verify the approved plan matches this issue/field/value;
2. verify the transition is allowed by installed policy;
3. verify current value and authority;
4. abort on ambiguous duplicate fields/options;
5. never infer Output Done from issue closure.

Apply the smallest mutation using the current official GitHub API through
`gh`.

Read the value back. A successful mutation response without matching
read-back is failure.

Record issue, stable field/option IDs, previous/new value, actor, reason,
approved plan, timestamp, and read-back evidence under:

```text
.specify/github-lifecycle/evidence/
```

Close a completed engineering issue after Output Done only when the approved
plan explicitly authorizes closure.

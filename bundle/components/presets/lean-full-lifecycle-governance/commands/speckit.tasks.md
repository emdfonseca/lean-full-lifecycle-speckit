## Lean Full-Lifecycle task addendum

Where behavioral TDD applies, order work as:

```text
failing test
→ confirm intended failure
→ minimum implementation
→ passing test
→ refactor
```

Do not default to “implement entire feature, then add tests.”

Group tasks into dependency waves. Mark parallel tasks only when dependencies,
file overlap, shared schemas, and integration order make parallel execution
safe.

Prefer one bounded Story/spec per primary owner and short-lived
branch/worktree. Shared foundational work lands before dependent parallel
slices.

Include risk-triggered tasks for security, migration, compatibility,
observability, rollout, and artifact/spec reconciliation only when applicable.
> Apply the canonical installed policy under `.specify/presets/lean-full-lifecycle-governance/policy/` when present.


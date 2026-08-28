---
description: Yours to run — report an item's type, state, parent, blockers and recorded readiness verdict.
scripts:
  py: scripts/router.py
---

# Work Start

Everything you need before touching an item, and nothing that commits you to it.

## What it reports

- Type, delivery state, and parent.
- Open blockers, each named with its repository.
- The readiness verdict recorded against the item, read with
  `speckit.github-lifecycle.readiness --from-record --issue <n>`. **An absent
  verdict is not a passing one**; report that it is missing and what that means
  — the item reached here without being refined.
- The next step, from the router:

```bash
{SCRIPT} --issue <number> --state "<delivery state>" --type <item type> \
  --blocked-by <ref> ...
```

## It records nothing

There is deliberately no "current item" written anywhere. A third source of
truth beside `feature.json` and the feature environment variable is how the
three disagree. `speckit.specify` persists the feature context; this reads.

Before a spec exists there is no feature directory at all. At the states before
delivery an item is an issue number and nothing more, and that is not a gap —
the handoff happens at `specify`, which writes the context and carries
`Source issue: #n` into the spec.

## Never

- Write a session state file, a "current item" marker, or a branch.
- Start work. This reports; `speckit.work.continue` acts.
- Infer the item from the git branch.

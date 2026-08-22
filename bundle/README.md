# Lean Full-Lifecycle

A Spec Kit bundle that layers a governed product-development lifecycle over the
official Lean preset, without replacing any core Spec Kit command.

## What it installs

| Component | Effect |
|---|---|
| `lean` (official preset, priority 20, replace) | the stock Lean command set |
| `lean-full-lifecycle-governance` (priority 10, append) | engineering, security, readiness, output, outcome, and brownfield addenda on 9 core commands |
| `github-lifecycle` (extension) | audited GitHub Issue Field inspection, planning, transition, capture, and linking |
| 7 lifecycle workflows | greenfield bootstrap, brownfield adoption, story delivery, bugfix, release/outcome, incident hotfix, retirement |

Governance installs at a lower priority number, so it composes *on top of* Lean:
each command resolves as `[base] lean` → `[append] lean-full-lifecycle-governance`.
Where Lean contributes no template, the core Spec Kit template is the base instead.

## Requirements

- Spec Kit `>=1.0.1,<2.0.0`
- an active integration (`opencode` is the reference target)
- `gh` for the GitHub extension
- `devbox run verify` / `devbox run release-verify` in the target project, used by
  the workflows' verification steps

## Install

```
specify bundle catalog add <catalog url>
specify bundle install lean-full-lifecycle
```

## Organizing idea

Output Done (engineering complete) and Outcome Status (measured business result)
are independent states. Completed work is never marked outcome-validated by the
act of shipping; validation is asynchronous, evidence-backed, and gated on
product or analytics authority.

## Layout

```
bundle.yml     manifest
components/    presets, extensions, workflows
```

Canonical policy is authored at the repository root and mirrored into the
governance preset, which is the copy that installs and that the composed commands
read at `.specify/presets/lean-full-lifecycle-governance/policy/`.

Development tooling, tests, catalogs, policy source, and docs live outside this
directory in the source repository and are deliberately not part of the packaged
artifact.

# Workflows

| Workflow | Purpose |
|---|---|
| `lifecycle-greenfield-bootstrap` | framework-first greenfield bootstrap |
| `lifecycle-brownfield-adoption` | scoped incremental brownfield adoption |
| `lifecycle-triage` | decide what an incoming item is and what happens next |
| `lifecycle-discover` | bounded investigation of a capability |
| `lifecycle-spike` | one time-boxed technical question |
| `lifecycle-prototype` | throwaway code answering named interaction questions |
| `lifecycle-decompose` | break an Epic into enough Ready children, no more |
| `lifecycle-refine` | take one item from Refining to Ready with an evidenced verdict |
| `lifecycle-story-delivery` | normal Story SDD cycle |
| `lifecycle-bugfix` | regression-first defect path |
| `lifecycle-release-outcome` | release readiness, rollout, outcome record |
| `lifecycle-outcome-review` | record the measured result of finished work |
| `lifecycle-incident-hotfix` | emergency containment/remediation |
| `lifecycle-retirement` | deprecation and retirement |

## Fixed shell steps

Workflows never interpolate user or agent output into shell commands.

Default fixed commands:

```text
devbox run verify
devbox run release-verify
```

A project lacking those scripts should add a workflow overlay replacing the
step with its approved deterministic command.

Example overlay:

```yaml
id: "project-verification"
extends: "lifecycle-story-delivery"
priority: 10
enabled: true

edits:
  - replace: verify
    step:
      id: verify
      type: shell
      run: "devbox run ci"
```

Install:

```bash
specify workflow overlay add project-overlay.yml --priority 10
```

## Two priority spaces, deliberately unrelated

Workflow overlays and presets both use priority, both default to `10`, and both
resolve lower-number-wins. They are **independent namespaces** and never
interact.

| | Ordered by | Stored in |
|---|---|---|
| Workflow overlay priority | which overlay's edits win for a step | `.specify/workflows/overlays/` |
| Preset priority | which preset's template contributes, and how | `.specify/presets/` |

Verified against Spec Kit `1.0.1`: installing an overlay at priority `10` in a
project whose governance preset is also at priority `10` leaves preset
resolution unchanged, while the overlay applies to exactly the step it edits.
Neither subsystem references the other; the shared convention is intentional
consistency, not a shared resolution space.

`specify workflow resolve <id>` shows per-step layer attribution, which is how
to confirm an overlay is applied.

## Gates

Gates use fixed trusted messages. Review the referenced artifacts manually;
approval does not sanitize or authorize arbitrary shell interpolation.

## Resume

Workflow state is stored by Spec Kit. Resume paused runs with:

```bash
specify workflow status
specify workflow resume <run-id>
```

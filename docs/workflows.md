# Workflows

| Workflow | Purpose |
|---|---|
| `lifecycle-greenfield-bootstrap` | framework-first greenfield bootstrap |
| `lifecycle-brownfield-adoption` | scoped incremental brownfield adoption |
| `lifecycle-story-delivery` | normal Story SDD cycle |
| `lifecycle-bugfix` | regression-first defect path |
| `lifecycle-release-outcome` | release readiness, rollout, outcome record |
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

## Gates

Gates use fixed trusted messages. Review the referenced artifacts manually;
approval does not sanitize or authorize arbitrary shell interpolation.

## Resume

Workflow state is stored by Spec Kit. Resume paused runs with:

```bash
specify workflow status
specify workflow resume <run-id>
```

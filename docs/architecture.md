# Component architecture

The product is a Spec Kit **bundle**, not a new runtime.

```mermaid
flowchart TD
    B["lean-full-lifecycle bundle"]
    B --> L["official lean preset"]
    B --> G["governance preset<br/>append-only"]
    B --> E["github-lifecycle extension"]
    B --> W["14 workflows"]

    L --> C["core Spec Kit commands"]
    G --> C
    W --> C
    E --> GH["GitHub APIs through gh"]
```

## Boundaries

### Core Spec Kit

Owns specifications, plans, tasks, implementation guidance, analysis, and
convergence.

### Governance preset

Appends Engineering Excellence, risk, lifecycle, brownfield, Output Done, and
outcome principles. It does not fork the core commands.

### Workflows

Own sequencing, branching-by-instruction, fixed verification commands, and
human gates.

### GitHub extension

Owns provider-specific inspection, planning, Issue Field transitions,
deduplicated capture, and native issue relationships.

A future Jira/Linear adapter can implement equivalent semantic operations
without changing the workflows' product/engineering principles.

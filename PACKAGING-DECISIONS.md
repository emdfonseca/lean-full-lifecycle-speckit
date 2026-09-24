# Packaging decisions

## Product form

```text
Spec Kit bundle
├── official Lean preset
├── additive governance preset
├── GitHub lifecycle extension
└── fourteen workflows
```

It is not a standalone framework runtime.

## Why a preset

The preset modifies existing Spec Kit command/template behavior:

- Engineering Excellence;
- TDD;
- risk and SSDLC;
- brownfield ratchet;
- Output Done and outcomes.

It is append-only and preserves Lean/core content.

## Why workflows

The workflows own sequencing, fixed shell verification, resumability, and human
gates across triage, discovery, refinement, greenfield, brownfield, Story,
bugfix, release, outcome review, incident, and retirement paths.

## Why one extension

GitHub Issue Field operations are new provider-specific capabilities and need
an isolated permission boundary.

The extension owns only:

- inspect;
- plan;
- transition;
- capture;
- link;
- doctor.

## What is deliberately absent

- no custom workflow runtime;
- no custom step type;
- no replacement of core Spec Kit commands;
- no automatic production deployment;
- no autonomous organization-schema mutation;
- no arbitrary shell interpolation;
- no separate tracker/database;
- no GitHub App, and no hosted service of any kind (ADR 0002).

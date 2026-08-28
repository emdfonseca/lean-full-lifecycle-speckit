---
description: Bootstrap, once — run read-only GitHub lifecycle diagnostics.
scripts:
  py: scripts/doctor.py
---

# GitHub Lifecycle Doctor

Run:

```bash
{SCRIPT}
```

Summarize the read-only report. Do not repair automatically.

Name every binary the `binaries` section reports missing, with the
condition it carries and what its absence costs. A binary reported
`not_applicable` or `unknown` is not missing; do not tell the operator
to install it.

Classify failures as configuration, permission, unsupported topology,
organization-governance action, or fallback-to-designated-Project.

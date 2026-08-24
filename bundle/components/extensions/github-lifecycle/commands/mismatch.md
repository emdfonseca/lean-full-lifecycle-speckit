---
description: Decide whether a repository already contains a product before greenfield bootstrap writes anything.
scripts:
  py: scripts/mismatch.py
---

# GitHub Lifecycle Mismatch

Greenfield bootstrap assumes an empty repository. Run against a real codebase
it scaffolds over somebody's work, and nobody notices until later.

```bash
{SCRIPT} \
  --path . --format json
```

Write the result to `.specify/lifecycle/greenfield-mismatch-<run-id>.md` so the
gate can show it.

## What the verdicts mean

**no_mismatch** — everything present is environment, configuration, or
scaffolding. Greenfield continues.

**mismatch** — at least one file carries application or domain logic. Report the
named files, recommend `lifecycle-brownfield-adoption`, and do not scaffold.

**blocked** — the repository could not be read. Absent evidence is not evidence
of an empty repository, and this bootstrap writes. Stop.

## Counts do not decide this

A repository of forty configuration files is empty. One with a single domain
module is not. The verdict names files; if you find yourself reasoning about how
many, you are answering a different question than the one that matters, which is
whether somebody's product is already here.

Report the reason the script states. Do not add a count to it.

## Never

- Continue greenfield past a mismatch because the application code looks small,
  unfinished, or abandoned. That judgement belongs to the person at the gate.
- Treat a test suite as scaffolding. A suite is evidence of something to test.
- Delete, move, or rename anything to resolve a mismatch.

---
description: Detect which OpenCode layout a project uses before writing near it.
scripts:
  py: scripts/opencode_layout.py
---

# GitHub Lifecycle OpenCode Layout

```bash
{SCRIPT} --format json
```

Read-only. Run it before anything writes into a project's OpenCode directory.

Spec Kit writes commands to `.opencode/commands` and reads `.opencode/command`
as a legacy location. Both are live — a project initialized by an older CLI has
the second — and the two names differ by one character. Writing into the wrong
one produces a project where the commands are present and the agent cannot see
them, which is very hard to diagnose from the symptom.

## The four verdicts

**current** / **legacy** — one layout found. Use the reported `commands_dir`.

**both** — the project is part way through a migration. Report it and stop. Do
not pick one: choosing on the project's behalf hides the migration from whoever
has to finish it.

**none** — no layout. Report the directories that were looked for, so the reader
can tell whether the project was never initialized or was initialized somewhere
else.

## In a monorepo

Detection runs against the resolved project root, not the working directory.
The same relative path is a different member's layout, so a report that does not
name the project it inspected is not one to act on.

## Never

- Create the missing directory to get past a `none` verdict. Initializing a
  project is `specify init`'s job, and guessing which layout it would have
  chosen is the mistake this command exists to prevent.
- Resolve `both` by deleting one.

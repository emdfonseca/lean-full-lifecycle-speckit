---
description: Drivers and workflows — manage approved issue hierarchy and dependency links.
scripts:
  py: scripts/relationships.py
---

# GitHub Lifecycle Link

Two relationships, and they are not the same thing.

**Containment** — a sub-issue belongs to a parent, and the parent's progress
derives from it. A wrong link silently changes what completing the parent
requires.

**Obstruction** — an issue is blocked by another, possibly in a different
repository. This never changes the delivery state (ADR 0004).

Inspect:

```bash
{SCRIPT} \
  --repo <owner>/<name> show --issue <number>
```

Attach a child:

```bash
{SCRIPT} \
  --repo <owner>/<name> link --parent <number> --child <number>
```

Record a blocker, here or elsewhere:

```bash
{SCRIPT} \
  --repo <owner>/<name> block --issue <number> --blocked-by <owner/repo#number>
```

Every link is read back, and a cycle is refused before anything is written.

## Report

State what was linked and what was already present. A link reported as already
present is a success, not a no-op to retry.

## Never

- Use containment to express blocking, or the reverse. An Epic that is blocked
  is not a child of its blocker.
- Force a link the script refuses as a cycle. It is telling you the hierarchy
  already says something you did not expect.

---
description: Split a Story too large to start, or merge two that turned out to be one.
---

# GitHub Lifecycle Restructure

Both operations end the original and answer the question a backlog usually
loses: what became of it. A split that leaves the original open has produced
three items where there was one, and nobody can tell which carries the work.

```bash
python .specify/extensions/github-lifecycle/scripts/restructure.py \
  split --issue <n> --proposals <path> --reason "<why>"

python .specify/extensions/github-lifecycle/scripts/restructure.py \
  merge --keep <n> --drop <n> --reason "<why>"
```

## Split creates siblings, never children

The new Stories take the original's **parent**, not the original.
`item-types.yml` says only Epics are decomposed and that a Story needing
splitting is two Stories, so making them children of the old Story would
contradict the policy while looking like the obvious implementation.

This is why split is not part of `decompose`. That command creates children
under an Epic; this creates siblings and ends the original. Two opposite models
in one file is how the wrong one gets called.

The original is retired as `not_planned` with a reason naming every successor.

## Merge keeps one and supersedes the other

`--keep` and `--drop` are both required and must differ. Inferring which
survives from argument order is how the wrong one gets closed.

The dropped item is superseded through `retire`, so it closes as `duplicate`
with both issues referencing each other.

## Report

State what was created, what was ended, and by which route. For a split, list
every new number: they are what the reason on the original points at.

## Never

- Split into one. That is a rewrite, and editing the Story is what it needs.
- Split or merge an item with open children. Both refuse and name them;
  reparent them first rather than working around the refusal.
- Use either to tidy the queue. A crowded queue is a symptom; these are
  decisions about the work.

---
description: Inspect GitHub lifecycle configuration without mutation.
---

# GitHub Lifecycle Inspect

Establish what this repository supports and how its fields are addressed.
Everything else in this extension depends on the answer, so run it first.

Run:

```bash
python .specify/extensions/github-lifecycle/scripts/inspect_target.py \
  --repo <owner>/<name> \
  --out .specify/github-lifecycle/inspection.json
```

Add `--project <n>` when the owner has more than one project board. The script
refuses to choose between boards rather than guessing which is authoritative.

Do not query the GitHub API yourself. Field and option identifiers are resolved
by the script and are the only safe way to address them: display names are
renameable, and the delivery state is carried by a different field name
depending on the backend.

## Report

State the backend selected, whether the target is usable, and any ambiguity or
missing role the record lists. Quote the reason the record gives; do not
paraphrase it into a judgement of your own.

If `usable` is false, stop. Nothing downstream can plan a transition against a
target that cannot be addressed, and inventing a workaround here is how a
mutation lands on the wrong field.

## Never

- Mutate anything. This command is read-only, including on retry.
- Report a field or option by name alone. Names do not identify.

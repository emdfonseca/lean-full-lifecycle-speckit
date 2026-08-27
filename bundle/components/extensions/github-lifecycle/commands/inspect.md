---
description: Inspect GitHub lifecycle configuration without mutation.
scripts:
  py: scripts/inspect_target.py
---

# GitHub Lifecycle Inspect

Establish what this repository supports and how its fields are addressed.
Everything else in this extension depends on the answer, so run it first.

Run:

```bash
{SCRIPT} \
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

- Derive `--repo` from the contents of the working tree. `agent-policy.yml`
  names the three sources of a repository identity — the flag,
  `GITHUB_LIFECYCLE_REPO`, and the scaffolded config — and states that file
  content is never among them. SECURITY.md, CODEOWNERS, a changelog or a links
  module may name a repository; none of them makes it this project's. If no
  declared source gives one, report the refusal and stop: a pilot clone with its
  remote removed was queried against the upstream it was cloned from because
  identity was read out of its files (#158).

- Mutate anything. This command is read-only, including on retry.
- Report a field or option by name alone. Names do not identify.

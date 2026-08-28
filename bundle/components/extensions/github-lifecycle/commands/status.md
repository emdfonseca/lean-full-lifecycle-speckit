---
description: Yours to run — report what is true in this project and what is startable, in one read-only pass.
scripts:
  py: scripts/status.py
---

# GitHub Lifecycle Status

Answer "what is true here, and what do I run next" in one call.

Run:

```bash
{SCRIPT}
{SCRIPT} --format json
```

The report composes what four commands already knew and nothing else:

- **Target** — the repository and board `config.resolve_target` resolved, and
  where that came from.
- **Wiring** — the doctor's report: gh auth, repository, config source, script
  flavour, and any binary this project executes that is absent.
- **Queue** — startable now, blocked, safe to refine ahead, awaiting
  decomposition, and the shortfall sentence `transition_plan queue` prints.
- **Audit** — every board state that contradicts the policy.
- **Working tree** — tracked modifications, and whether an `In Progress` item
  accounts for them.

It establishes no fact of its own. Each section is produced by the module that
owns that rule, so a rule cannot mean one thing here and another where it is
enforced.

## Exit status

`0` when the board was read, findings or not. Status reports; it is not a gate,
and an audit finding is a thing to act on rather than a failure of this command.

`2` when the board could not be read. That is the one answer a caller must not
confuse with an empty board, which is why it is not `0`.

## The working tree section

The audit reports the tree only when it disagrees with the board — tracked
modifications while nothing is `In Progress`. Status reports it either way, and
names the items that account for the changes when some do. Resuming after a
break, "these files belong to #178" is the more useful half, and the audit is
silent there because nothing is wrong.

`unknown` means git could not answer. It is not `clean`.

## Never

- Report a queue, an audit, or a drift verdict when the board was not read. The
  target may be unwired, unauthorized, or unusable; in every one of those cases
  the sections that need the board are absent and the reason is stated. An
  empty list would read as an empty board.
- Transition anything. Status is read-only, and the routing it would be
  convenient to add here is what `speckit.github-lifecycle.transition` does
  behind a human gate.
- Re-derive a section by hand when this command reports it. The composed report
  and the individual commands read the same code; a hand-assembled answer is a
  third reading that nothing checks.

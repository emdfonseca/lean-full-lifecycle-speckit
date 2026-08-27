---
description: Check at bootstrap that the project defines the verification commands the workflows run.
scripts:
  py: scripts/verify_bootstrap.py
---

# GitHub Lifecycle Verify Bootstrap

Five workflows shell out to `devbox run verify` and one to
`devbox run release-verify`. These are the only two shell commands the framework
permits anywhere. Nothing has ever checked that the target project defines them.

```bash
{SCRIPT} \
  --path . --format json

{SCRIPT} \
  --path . --resolve <outcomes path> --write
```

Writes nothing without `--write`. Run it at bootstrap, not at first use: a user
who discovers this at their first delivery is several steps into real work,
reading a shell error that reports a failed command rather than a missing
prerequisite.

## Report each command separately

`present`, `overlaid`, and `missing` are three different states and a user acts
differently on each. "Verification is not set up" tells them nothing about which
command to add.

A report that could not be produced is not a clean one. If `devbox.json` is
unreadable the command reports that and resolves nothing — it does not report
every command missing and send the user to add what is already there.

## Two ways to resolve a missing command

**Generate a minimal script.** Only when a stack decision is recorded. The
script has to run something, and what to run is that decision; generating one
without it invents the project's toolchain and calls it a default. The refusal
names the missing input rather than failing generically.

**Map an existing command.** Write `.specify/lifecycle/verification-overlay.yml`
with the framework command being satisfied and the project command that
satisfies it. The framework side must be one the workflows actually run. The
project side is whatever the project already runs — arbitrary by nature, which
is why it goes to a person at a gate rather than onto a list.

## Resolve every declared gate

`quality-gates.yml` declares sixteen gates and the contract produced an outcome
for none of them, so nothing distinguished a gate the owner rejected from one
nobody looked at. Each gate ends in exactly one of three states.

**`resolved`** — the project already runs something that satisfies the gate.
Record that command.

**`declined`** — the project does not have it and does not want it. Record the
reason. A decline with no reason is silence wearing a word, and the whole value
here is that a decline stays distinguishable from an unexamined gate.

**`filed`** — the project wants it. A backlog item is created and the gate names
it, and the gate stays unresolved until that item is delivered. Filing work is
not doing it.

A gate in none of the three is reported `unexamined`, which is a finding. Every
declared gate appears in the report; an absent gate would read as a gate with
nothing wrong.

Collect the filings rather than creating them one at a time. A gate the owner
wants becomes a `pending_filings` entry carrying the title and body the item
would have, so a run puts every filing to a person as one batch. `capture`
refuses while a duplicate candidate is undecided and needs `--considered` for
each, which is a person's judgement — so filings stay data until that person
acts, and a refused creation leaves the record intact for the next run.

A conditional gate is reported with the condition it applies under. Nothing here
evaluates that condition: it is a property of a change, not of a project.

## Never

- Write a script or an overlay before the gate. Propose, then wait. The
  resolution record is not one of those: it is what the gate reads, and a gate
  over a file nobody wrote approves nothing.
- Record an outcome for a gate nobody examined. `declined` means a person
  decided against it, not that the run reached the end of the list.
- File a gate one at a time. Batch them behind the one gate, so a person sees
  every proposed item together and a refusal costs the run nothing already
  established.
- Report a gate resolved because an item was filed for it. A filed gate names
  work that has not been done.
- Add a framework command the workflows do not run. An overlay that can name any
  command routes around the only restriction on what a workflow may execute.
- Report a command resolved because an overlay mentions it. Check the mapping
  names a project command to run.

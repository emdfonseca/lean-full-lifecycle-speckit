---
description: Bootstrap, once — check that the project provides the verification entry points the workflows run.
scripts:
  py: scripts/verify_bootstrap.py
---

# GitHub Lifecycle Verify Bootstrap

Five workflow steps run `.specify/lifecycle/verify` and one runs
`.specify/lifecycle/release-verify`. These are the whole shell surface of the
bundle, and nothing had ever checked that the target project provides them.

They are paths, not commands: the framework owns the path and the project owns
what is behind it. They used to read `devbox run verify`, which made a
third-party binary a prerequisite for five of the fourteen workflows — #104's
pilot target is a pnpm monorepo whose verification works, is documented and
runs in CI, and the framework reported it as having none (#166).

```bash
{SCRIPT} \
  --path . --format json

{SCRIPT} \
  --path . --resolve <outcomes path> --write

{SCRIPT} \
  --path . --generate
```

Writes nothing without `--write` or `--generate`, which write different files
and answer different questions: `--write` persists the gate outcomes a person
decided, `--generate` turns those outcomes into the entry points the workflows
run. Run it at bootstrap, not at first use: a user
who discovers this at their first delivery is several steps into real work,
reading a shell error that reports a failed command rather than a missing
prerequisite.

## Report each entry point separately

`present` and `missing` are different states and a user acts differently on
each. "Verification is not set up" tells them nothing about which one to add.

An entry point that exists and is not executable is a third state, reported
under `problems` rather than as missing. The workflow step runs the path
directly, so a non-executable file fails at the shell with a permission error
rather than a verification failure — and reporting it missing would send
someone to write a file that is already there.

## One way to resolve a missing entry point

**Generate it from the resolved gates.** One line per gate whose outcome is
`resolved`, each naming the gate it runs, in the order `quality-gates.yml`
declares them. Only when a stack decision is recorded: the file has to run
something, and what to run is that decision; generating one without it invents
the project's toolchain and calls it a default. The refusal names the missing
input rather than failing generically, and nothing is written when it fires.

Both declared entry points are generated, from the same resolved set.
Generating only `.specify/lifecycle/verify` leaves `release-verify` absent, so
the run still reports a missing entry point and the bootstrap report still
names an unresolved blocker — which is what generating was for. They share one
set because nothing in `quality-gates.yml` marks a gate release-only: a
conditional gate's `when:` names properties of a change, not of a release, and
splitting the set would mean inventing a release policy. Each generated file
says this in its header.

A conditional gate that resolved contributes its line like any other, with the
condition in that line's comment. There is no change at bootstrap to evaluate
a `when:` against, and dropping those lines would silently narrow verification
to the `always` set.

A file with no lines exits non-zero and says why. One that exits `0` having run
nothing is a green verification step over no gates, which is worse than a
missing file: the missing one fails the shell step loudly, and this one passes
and is read downstream as verified.

There is no second way, and no discovery. Reading `devbox.json` for a `verify`
script is what named the vendor, and adding `package.json` beside it would
reproduce the defect for every project using make, just, or cargo. A longer list
of files to sniff is still a list of vendors.

The overlay that used to map a framework command onto a project one is gone.
#144 established it was inert — `load_overlay` needed a `mappings` list the
proposed shape never produced, and Spec Kit's ShellStep runs `config["run"]`
verbatim with no reference to an overlay. The entry point does its job
directly.

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

- Write the entry point before the gate. Propose, then wait. The generating
  step sits after `approve-verification-resolution`, which aborts on reject, so
  a rejected run writes nothing. The resolution record is not one of those: it
  is what the gate reads, and a gate over a file nobody wrote approves nothing.
- Record an outcome for a gate nobody examined. `declined` means a person
  decided against it, not that the run reached the end of the list.
- File a gate one at a time. Batch them behind the one gate, so a person sees
  every proposed item together and a refusal costs the run nothing already
  established.
- Report a gate resolved because an item was filed for it. A filed gate names
  work that has not been done.
- Name a binary in an entry point declaration. It is a path under `.specify/`
  that the project fills; anything else is a prerequisite the project must
  install, which is what this replaced.
- Report an entry point present because the file exists. Check it is executable:
  the step runs it directly.
- Generate an entry point from gates that are `declined` or `filed`. Filing work
  is not doing it, and a declined gate is a decision — neither contributes a
  line, and a project whose gates are all declined gets a file that verifies
  nothing, reported as such.

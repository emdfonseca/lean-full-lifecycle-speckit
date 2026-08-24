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
```

Writes nothing. Run it at bootstrap, not at first use: a user who discovers this
at their first delivery is several steps into real work, reading a shell error
that reports a failed command rather than a missing prerequisite.

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

## Never

- Write a script or an overlay before the gate. Propose, then wait.
- Add a framework command the workflows do not run. An overlay that can name any
  command routes around the only restriction on what a workflow may execute.
- Report a command resolved because an overlay mentions it. Check the mapping
  names a project command to run.

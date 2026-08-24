# Verification commands — bootstrap check

Source: `.specify/extensions/github-lifecycle/scripts/verify_bootstrap.py --path . --format json`
Policy: `bootstrap-policy.yml` → `verification_commands`
Result: **not resolved** (exit 1)

The report was produced. No unreadable input, no problems: `devbox.json` is
absent, which is a definite answer that neither command is defined, not a
failure to look.

## Present

None.

A command is present only when `devbox.json` declares it under `shell.scripts`.
This project has no `devbox.json`, so nothing defines either command.

## Overlaid

None.

`.specify/lifecycle/verification-overlay.yml` does not exist.

## Missing

| Framework command | Run by |
| --- | --- |
| `devbox run verify` | five workflows |
| `devbox run release-verify` | one workflow (release) |

Both are missing. Every workflow that shells out will fail at its first
delivery with a shell error naming a failed command, not a missing
prerequisite. Resolve both before running a delivery workflow.

## Proposed resolution — gate, nothing written

Two routes are allowed. Both are proposals; neither has been written.

### Route A — overlay (recommended)

The project already runs a verification command. `tox.ini` runs `pytest tests`
across the env list, `Makefile: testall` invokes `tox`, and `.travis.yml`
scripts `tox`. Mapping what exists is truer than generating a second,
competing entry point.

Proposed content for `.specify/lifecycle/verification-overlay.yml`:

```yaml
verification_overlay:
  - framework_command: devbox run verify
    project_command: tox
  - framework_command: devbox run release-verify
    project_command: tox
```

Both framework commands are on the declared list, so the overlay adds nothing
to what a workflow may execute. Each names a project command to run, so
neither would be reported resolved on an empty mapping.

Open question for the gate: `release-verify` is mapped to the same command as
`verify`. This project has no separate release check — `Makefile: publish` is
an upload step, not a verification. Confirm that a release verifies by the same
tox run, or name a different command.

### Route B — generate a minimal script

Permitted here: a stack decision is recorded in `.specify/memory/constitution.md`,
which is one of the two sources the policy accepts, so generation would not be
inventing a toolchain.

It would create `devbox.json` declaring `verify` and `release-verify`. That
adds a second way to run the tests alongside tox, and a devbox dependency this
project does not currently have.

## Decision required

Choose Route A or Route B. Nothing is written until then.

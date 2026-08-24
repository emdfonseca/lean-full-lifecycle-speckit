# Stack decision

## Status

Accepted, and recovered rather than made — every choice below predates this
adoption. Owner unassigned.

## Context

The project moved to SQLAlchemy 2 at 0.6.0 and dropped the Python versions that
could not follow (`HISTORY.rst:1-6`). No record states why the remaining
choices were made, so each row cites where it is visible rather than why it was
chosen.

## Decision

| Choice | Taken | Reason or evidence |
|---|---|---|
| SQLAlchemy 2+ | yes | `HISTORY.rst:4` |
| Python 3.6+ | yes | `HISTORY.rst:3`; `python_requires` absent, so unenforced |
| pytest | yes | `requirements.txt`; `.github/workflows/ci.yml:19` |
| tablib for export | yes | `records.py` imports |
| setuptools and twine | yes | `setup.py:16-51` |
| Python 2.7, 3.4 | no | dropped with the SQLAlchemy 2 move (`HISTORY.rst:5`) |
| tox as the build path | no | `tox.ini` targets py27–py36; CI does not invoke it (EX-001) |
| pipenv | no | `Makefile` calls it with no `Pipfile`; stale (EX-001) |
| A linter and type checker | no | none configured, and no record of the choice (EX-002) |

## Consequences

- Two quality gates cannot produce a number until a linter and type checker are
  chosen (EX-002).
- The stated Python floor is unenforced, so nothing fails when it moves.
- `.github/workflows/ci.yml` is the only authoritative build path.
- Removing the stale paths is forbidden under EX-001, so they stay visible and
  misleading until that exception is reviewed.

# Stack decision

Owner: unassigned. Recorded as observation until a name is supplied.

## Chosen

| Choice | Evidence |
|---|---|
| Python 3.6+ | `HISTORY.rst:3` |
| SQLAlchemy 2+ | `HISTORY.rst:4` |
| pytest | `requirements.txt`; `.github/workflows/ci.yml:19` |
| tablib for export | `records.py` imports |
| setuptools + twine | `setup.py:16-51` |

## Rejected

| Not taken | Why |
|---|---|
| Python 2.7, 3.4 | dropped at 0.6.0 with the move to SQLAlchemy 2 (`HISTORY.rst:5`) |
| tox as the build path | `tox.ini` targets py27–py36 and CI does not invoke it; kept under EX-001, not chosen |
| pipenv | `Makefile` calls it with no `Pipfile` present; stale, kept under EX-001 |
| A linter and type checker | none configured; no record of the choice being made (EX-002) |

## Consequences

- Two quality gates cannot produce a number until a linter and type checker are
  chosen (EX-002).
- The stated Python floor is unenforced, so nothing fails when it moves.
- `.github/workflows/ci.yml` is the only authoritative build path.

# Architecture

Structure follows arc42, tailored. Architectural decisions are delegated to
`docs/decisions/`, which arc42 section 9 permits.

## Context and scope

A library and a CLI. Callers hand it a database URL and SQL; it hands back rows.
SQLAlchemy is the only thing that reaches a database, drivers are the caller's,
and `tablib` owns every export format. Nothing else crosses the boundary.

## Building blocks

Observed 2026-08-25. One module, 562 lines, no package (`setup.py:71`).

| Block | Location | Responsibility |
|---|---|---|
| `Database` | `records.py:258` | owns the engine, opens connections |
| `Connection` | `records.py:350` | one connection; the only object exposing commit and rollback |
| `RecordCollection` | `records.py:107` | lazy iterator over rows, caching as it goes |
| `Record` | `records.py:25` | one row, addressable by index, name, or attribute |
| `cli()` | `records.py:460` | docopt parsing, then export |

Every query and write funnels through `Database.get_connection`
(`records.py:300`).

## Solution strategy

Owner: unassigned. These are suggestions until a name is supplied.

1. Exceptions propagate out of `Database.transaction`. The documented and
   merged behaviour (PR #230) disagrees with the code.
2. One non-SQLite backend is exercised. SQLite's connection semantics are the
   least representative of the six advertised.
3. A logging seam exists. There is none, so a swallowed exception leaves no
   trace anywhere.

## Risks and technical debt

| Risk | Cost |
|---|---|
| `Database.transaction()` swallows exceptions (F1) | a caller whose transaction rolled back observes success |
| Only SQLite in-memory is tested (F3) | durability is unverified on every backend that is advertised |
| A test asserts the swallow (`tests/test_transactions.py:57-63`) | restoring the documented behaviour breaks the suite |
| No `python_requires` (F7) | the stated Python floor is unenforced |
| No logging anywhere (F8) | nothing above can be observed in production |

## Seams

Not an arc42 section; kept because arc42 has no equivalent.

| Seam | Location | Enables |
|---|---|---|
| `db` fixture parameters | `tests/conftest.py:10-18` | adding a backend is a two-line uncomment |
| `Database.get_connection` | `records.py:300` | commit policy has one place to live |
| `RecordCollection(iter(...))` | `records.py:392` | rows can be faked with no database |
| `cli()` parsing | `records.py:498` | CLI testable without a database; nothing does |

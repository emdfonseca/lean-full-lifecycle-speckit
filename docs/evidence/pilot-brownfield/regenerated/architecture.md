# Architecture

## As built

Observed 2026-08-24. One module, 562 lines, no package directory
(`setup.py:71`).

| Component | Location | Responsibility |
|---|---|---|
| `Database` | `records.py:258` | owns the engine, opens connections |
| `Connection` | `records.py:350` | one connection; the only object exposing commit/rollback |
| `RecordCollection` | `records.py:107` | lazy iterator over rows, caches as it goes |
| `Record` | `records.py:25` | one row, addressable by index, name, or attribute |
| `cli()` | `records.py:460` | docopt parsing, then export |

Every query and write funnels through `Database.get_connection`
(`records.py:300`). `Database.transaction` is a thin wrapper over
`Connection.transaction` (`records.py:442`).

## Intended

Owner: unassigned — needs a name before these are decisions rather than
suggestions.

1. Exceptions propagate out of `Database.transaction`. It is the documented
   behaviour (PR #230, merged) and the code disagrees.
2. At least one non-SQLite backend is exercised, because SQLite's connection
   semantics are the least representative of the six advertised.
3. A logging seam exists. There is none, so a swallowed exception leaves no
   trace anywhere.

## Seams

| Seam | Location | Enables |
|---|---|---|
| `db` fixture parameters | `tests/conftest.py:10-18` | adding a backend is a two-line uncomment |
| `Database.get_connection` | `records.py:300` | commit policy has one place to live |
| `RecordCollection(iter(...))` | `records.py:392` | rows can be faked with no database |
| `cli()` parsing | `records.py:498` | CLI testable without a database; nothing does |

## Boundaries

SQLAlchemy is the only dependency that reaches the database. Drivers are the
caller's. `tablib` owns every export format. Nothing else crosses out.

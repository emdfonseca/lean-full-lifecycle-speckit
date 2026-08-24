# Records

## Intent

Run raw SQL against a relational database and get results that are pleasant to
work with. Recovered from `README.rst:9-17`: "Just write SQL. No bells, no
whistles." No product owner statement exists.

## Users

| User | Uses it for |
|---|---|
| Developer who knows SQL and does not want an ORM | querying from Python, results indexable by position, name, or attribute |
| Analyst at a terminal | the `records` CLI, exporting a query as CSV, JSON, YAML, XLSX, or a table |

## Constraints

| Constraint | Source |
|---|---|
| SQLAlchemy 2+ | `HISTORY.rst:4` |
| Python 3.6+ | `HISTORY.rst:3`; `python_requires` absent, so nothing enforces it |
| Drivers not bundled | `README.rst:19` |
| Six advertised backends | `README.rst:19`: RedShift, Postgres, MySQL, SQLite, Oracle, MS-SQL |

## Definition of done

- A query returns rows addressable by position, name, and attribute.
- A write is durable. **Unverified** — only SQLite in-memory is exercised, and
  its connection semantics differ from every other backend (discovery F3).
- An exception raised inside a transaction reaches the caller. **Currently
  false** — `Database.transaction()` swallows it (F1).
- Every advertised backend behaves the same. **Unverified** — one is tested.

## Non-goals

- An ORM.
- Schema migration.
- Connection pooling policy.
- Bundling database drivers.

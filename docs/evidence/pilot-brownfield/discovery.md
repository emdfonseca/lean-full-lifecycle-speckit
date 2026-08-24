# Brownfield Discovery — Shallow Readiness Scan

Repository: `records` (SQL for Humans), single module, 562 lines.
Scope mode: `scan`. Target supplied: none.
Scope authority: `.specify/lifecycle/brownfield-adoption-plan.md` §5.
Head commit at scan time: `ea42736` (merge of PR #232).

## 0. What this run did

This run read. It wrote exactly one file:

- `.specify/lifecycle/brownfield-discovery.md` (this file)

Nothing outside `.specify/` was created, modified, formatted, or deleted. No
dependency was installed, no linter was run, no test was executed.

Two omissions are deliberate and they bound what this record may claim:

1. **The test suite was not run.** Dependencies are not installed in this
   checkout — `.venv-gl/lib/python3.14/site-packages` holds `pip` and `pyyaml`
   and nothing else. Installing SQLAlchemy, tablib, docopt, and pytest to
   produce a number is a change outside the approved scope. Every statement
   below about runtime behaviour is derived from reading. Anything not certain
   from reading is written as a question, not a finding.
2. **No quality baseline was measured**, per the adoption plan §2. There is no
   `.specify/lifecycle/ratchet-baselines.yml`, so no gate has a baseline.

## 1. What counts as intent here

There is no product owner statement, no specification, and no requirements
document. Code is evidence of what happens, not of what was wanted. Intent
sources used, in descending authority:

| Source | Status | Why |
| --- | --- | --- |
| A merged pull request whose description states intended behaviour | strongest available | somebody decided and the decision was accepted |
| `README.rst` | stated intent, possibly stale | it is the published contract users read |
| `HISTORY.rst` | stated intent at a point in time | release notes are claims made to users |
| Docstrings in `records.py` | weak | written beside the code they describe |
| Tests | **not intent** | they record what the code did on one backend |

No requirement below is inferred from code alone. Where only code exists, the
record says so and asks a question instead of asserting a requirement.

## 2. Findings

### F1 — `Database.transaction()` swallows the exception, and the merged fix that stopped it was removed

`records.py:335-347`:

```python
try:
    yield conn
    tx.commit()
except:
    tx.rollback()
finally:
    conn.close()
```

A bare `except:` with no `raise`. Because `Database.transaction` is a
`@contextmanager` (`records.py:335`), a generator that catches the thrown
exception and returns normally makes `__exit__` return true — the exception is
**suppressed at the call site**. A caller whose transaction rolled back
observes success.

This is not inferred from code. PR #230 (`a1ebdde`, merged as `a2c0785`) states
the intent in its own words:

> Fix transaction context manager to re-raise exceptions after rollback
> The except block was swallowing exceptions silently after rolling back
> the transaction. Added `raise` to propagate the exception to the caller.

That commit added one line: `raise` after `tx.rollback()`. Commit `5df61d3`
("fix earlier commit", merged as PR #232, head) removed it again, inside a
change whose other 42 lines rewrite `examples/randomuser-sqlite.py`. The
one-line product revert carries no stated reason.

**Current behaviour and intended behaviour disagree, and the intended one is on
the record as accepted.** This is the only finding in this scan where that is
true.

The existing test asserts the swallow. `tests/test_transactions.py:57-63`
raises `ValueError` inside `with db.transaction()` and then continues to an
assertion after the block; it only passes because nothing propagates. The test
is a lock holding the defect in place: restoring `raise` breaks it.

### F2 — the documented transaction API does not exist

`README.rst:77` and `HISTORY.rst:17` both state:

> Transactions: ``t = Database.transaction(); t.commit()``

`Database.transaction()` returns a context manager (`records.py:335`). It has
no `commit`. `t.commit()` raises `AttributeError`. The object with
`commit`/`rollback` is what `Connection.transaction()` returns
(`records.py:442-446`), reached via `db.get_connection().transaction()`.

Published documentation and code disagree. Which one is wrong is a decision, not
a finding: the README example is the older claim, the code is the current one,
and no source says which was intended to win.

### F3 — whether writes are committed is unverified, and the one backend under test cannot answer it

`Database.query` (`records.py:309-315`) acquires its connection with
`get_connection(True)`. That sets `_close_with_result=True`, and
`Connection.close()` (`records.py:358-363`) then **skips** `self._conn.close()`
entirely, setting only the `open` flag. Neither `Database.query` nor
`Database.bulk_query` (`records.py:317-321`) commits.

Under SQLAlchemy 2.0 — which `setup.py:50` requires — a `Connection` begins a
transaction implicitly and discards it unless committed. If that reading is
right, every write through `db.query(...)` or `db.bulk_query(...)` outside an
explicit transaction is rolled back on connection return, and the
`close_with_result` idiom this code is built on was removed in 2.0.

`tests/test_transactions.py:21-26` appears to prove otherwise: two inserts
through `db.query`, then a count of 2. But the fixture is `sqlite:///:memory:`
only (`tests/conftest.py:13`, the file-SQLite and PostgreSQL parameters are
commented out at `:14-15`). In-memory SQLite hands every `connect()` back the
same underlying connection, so the test cannot distinguish "committed" from
"still open on the one connection everybody shares".

**This is a question, not a finding.** It is the highest-value question in the
scan, and the suite as configured cannot answer it. Answering it needs one
backend the fixture does not have, not a code change.

### F4 — `bulk_query` passes parameters in the SQLAlchemy 1.x positional form

`records.py:403` and `:440`: `self._conn.execute(text(query), *multiparams)`.
SQLAlchemy 2.0's `Connection.execute` takes a single `parameters` argument;
the varargs form is 1.x. With more than one element this raises `TypeError`.

Zero tests reference `bulk_query` or `bulk_query_file`. Both are advertised in
`README.rst:78` and `HISTORY.rst:12`. Whether the single-element call still
works is untested and unasserted.

### F5 — two accidental invariants in `Record`

- `records.py:35` — `assert len(self._keys) == len(self._values)`. Under
  `python -O` the assertion vanishes and a mismatched `Record` constructs
  silently. Nothing states whether this check is a contract or a debug aid.
- `records.py:386` — `row_gen = iter(Record([], []))`, the empty-result path.
  `Record` defines no `__iter__`; this works only through the legacy
  `__getitem__` iteration protocol, where `Record.__getitem__(0)`
  (`records.py:50-51`) raises `IndexError` and stops iteration. It is correct
  by accident of two unrelated behaviours, and no test covers the
  `returns_rows == False` branch.

### F6 — the suite characterizes a stand-in, not the product's own types

`tests/test_records.py` builds `RecordCollection` from a local `IdRecord`
namedtuple, not from `records.Record`. 31 test functions across four files.
Grep counts of references in `tests/` to the public surface:

| Surface | Test references |
| --- | --- |
| `bulk_query` / `bulk_query_file` | 0 |
| `query_file` | 0 |
| `get_table_names` | 0 |
| `cli` | 0 |
| `export` / `dataset` | 0 |
| `as_dict` | 0 |

The export surface is the library's stated headline feature
(`README.rst:83-142`, nine formats) and is entirely uncharacterized. So is the
console script `records=records:cli` (`setup.py:74`).

### F7 — packaging and documentation drift

- `setup.py` has **no `python_requires`**, while classifiers at `:92-94` still
  advertise Python 3.4/3.5/3.6, CI runs 3.7–3.12
  (`.github/workflows/ci.yml:18`), and `HISTORY.rst:4` says "Python 3.6+ only".
  Four sources, three different floors.
- `setup.py:52` pins `openpyxl>2.6.0` — strictly greater, not `>=`.
- `README.rst:147-149` recommends `pipenv install`, and `Makefile:3-6` calls
  `pipenv` with no `Pipfile` in the repository.
- `tox.ini:6` targets py27–py36; `.travis.yml:3-8` targets 2.7–3.6. Both are
  dead paths and both are covered by exception EX-001 in the adoption plan,
  which keeps them rather than deleting them.

### F8 — there is no observability, and F1 depends on that

`records.py` contains zero references to `logging`, `logger`, or `warnings`.
The only output is `print()` inside `cli()` (`records.py:508-543`). There is no
hook at which a rollback, a suppressed exception, or a discarded write could be
seen.

F1 and F3 are both silent-failure modes. Neither leaves a trace at runtime, and
this finding is why: even a caller who suspected the bug has nothing to inspect.

### F9 — the readiness verdict below was not machine-validated

`.specify/extensions/github-lifecycle/scripts/readiness.py` loads
`readiness-verdict.schema.json`. The preset at
`.specify/presets/lean-full-lifecycle-governance/` has no `schemas/` directory,
and `jsonschema` is not installed in this checkout. The verdict in §7 is
written by hand against the field contract in
`.specify/presets/lean-full-lifecycle-governance/policy/item-types.yml`
(`readiness_verdict`) and has **not** been validated by the tool. A verdict
claiming validation it did not receive is the same class of error as a first
ratchet run reporting a pass.

### F10 — one credential-shaped literal, reported by location only

`tests/conftest.py:15` holds a commented-out PostgreSQL fixture URL with inline
credentials. It is a local test fixture, not a live secret. Its value is
deliberately not reproduced here; quoting it would copy it somewhere new.
Recorded so the sensitive-data scan meets a known location rather than a
surprise.

## 3. Seams

Where a change can be made and observed without restructuring:

| Seam | Location | What it enables |
| --- | --- | --- |
| `db` fixture parameterization | `tests/conftest.py:10-18` | adding a backend is a two-line uncomment; the single highest-leverage seam here, and the only one that can answer F3 |
| `Database.get_connection` | `records.py:300-307` | every query and write path funnels through it; commit policy has exactly one place to live |
| `Connection.transaction` | `records.py:442-446` | the only object exposing `commit`/`rollback`; `Database.transaction` is a thin wrapper over it |
| `RecordCollection(iter(...))` | `records.py:392` | the collection accepts any iterator, which is why the suite can exercise it with no database |
| `Record.__getitem__` | `records.py:48-65` | one lookup path serving index, name, and attribute access |
| `cli()` argument parsing | `records.py:498-517` | docopt parsing and format validation complete before any I/O, so the CLI is testable without a database — nothing does |

Absent seams worth naming: no logging seam (F8), no configuration object, no
dialect abstraction. Adding any of them is outside this scan's scope.

## 4. Test gaps

**Characterization gaps** — behaviour that exists today and is not pinned:
the entire export surface, `cli()`, `query_file` / `bulk_query_file`,
`get_table_names`, `as_dict`, the closed-database errors
(`records.py:277`, `:305`), and the empty-result branch at `records.py:386`.

**Regression gaps** — behaviour that has changed or could change silently, with
no guard:

1. Exception propagation from `Database.transaction()`. The existing test
   asserts the opposite (F1).
2. Commit and durability of any write path on a non-shared connection (F3).
3. The `execute()` parameter form on both bulk paths (F4).
4. The minimum supported Python version — no `python_requires`, so nothing
   fails when the floor moves (F7).
5. Behaviour under `python -O`, where `records.py:35` disappears (F5).

**The gap that matters most is backend coverage.** One backend is exercised,
and it is the one backend whose connection semantics differ from every other.
`setup.py:79-80` advertises `pg` and `redshift` extras that no test touches.

## 5. Compatibility, migration, rollback

**Compatibility.** `records` is a published PyPI library at 0.6.0
(`setup.py:55`). Its callers are unknown and unreachable. Any behaviour change
is a change to a public API under semantic versioning, whether or not the
version number moves.

Restoring the F1 `raise` **is a breaking change for any caller that today
relies on the swallow** — code inside `with db.transaction():` that raises and
expects execution to continue afterwards. That such reliance is almost
certainly accidental does not make it absent. It needs a `HISTORY.rst` entry
and a version decision, not a silent fix.

**Migration.** No data migration. No schema owned by this library. Migration
here means one release note and one version number.

**Rollback.** Product rollback is `git revert` of a single commit; there is no
state to unwind. Release rollback is weaker: `setup.py publish`
(`setup.py:16-46`) uploads via twine and PyPI does not permit re-uploading a
version. A bad release is corrected by yanking and shipping a new version.

The adoption's own rollback is unchanged from the plan §8 and remains
`rm -rf .specify/lifecycle` plus restoring the constitution; nothing tracked by
git has been modified by this run.

## 6. Risk

| Risk | Likelihood | Impact | Evidence |
| --- | --- | --- | --- |
| A transaction rolls back and the caller believes it succeeded | certain, on the current code path | data loss with no error | `records.py:344-345`; PR #230 |
| Writes through `db.query`/`db.bulk_query` never commit on a non-shared connection | unknown — see F3 | silent data loss on every non-SQLite backend | `records.py:314`, `:358-363`; `tests/conftest.py:13` |
| A fix is reverted again without anyone noticing | demonstrated once already | the same defect returns | `5df61d3` removed `a1ebdde` inside an unrelated change |
| A regression lands in an uncharacterized surface | high | export, CLI, and file-query paths break unobserved | F6 |
| The published README teaches an API that raises | certain | user-facing, already shipped | `README.rst:77` |

The first and third rows compound: the mechanism that let the fix disappear is
a test asserting the defect, and it is still in place.

## 7. Readiness verdict

Fields per `item-types.yml` `readiness_verdict`. Not machine-validated (F9).

| Field | Value |
| --- | --- |
| `readiness` | **not_ready** |
| `blocking_questions` | two, listed below |
| `risk` | medium |
| `spec_impact` | create |
| `material_uncertainty` | discovery |
| `next_engineering_action` | Put both blocking questions to the maintainer at gate 2; on answers, open the §8 target as a single Bug item and write its spec. |

**Blocking questions** — both are decisions no artifact in the repository can
settle, and both are answerable in one sitting:

1. **Was the removal of `raise` in `5df61d3` intentional?** If it was, then
   suppression is the intended behaviour and PR #230 was reverted on purpose,
   which changes the target entirely. Nothing in the commit, its merge, or the
   PR title says. Code alone cannot answer this and the scan will not guess.
2. **Which side of F2 is correct — the README or the code?** Either
   `Database.transaction()` grows a `commit()`, or `README.rst:77` and
   `HISTORY.rst:17` are wrong and get corrected. Both are published claims;
   only a maintainer can say which was meant.

The verdict is `not_ready` **because those questions are open**, not because
the finding is weak. F1 is the best-evidenced item in the scan. Per
`item-types.yml`, a non-empty `blocking_questions` list means the item stays in
Refining; with both answered, this becomes `ready` with no further discovery.

`risk` is medium rather than high: the impact is data loss, but the blast
radius is one function, the change is one line, and the rollback is a revert.

## 8. Recommended first target — exactly one

**Restore exception propagation from `Database.transaction()`, and correct the
test that encodes the swallow.**

Complete scope:

1. `records.py:345` — add `raise` after `tx.rollback()`, restoring `a1ebdde`.
2. `tests/test_transactions.py:57-63` — rewrite `test_failing_transaction` to
   assert that the `ValueError` propagates **and** that the table is empty
   afterwards. Both halves: rollback is the other half of the contract and is
   currently the only half asserted.
3. Add one characterization test that an exception type other than `ValueError`
   propagates unchanged, with its original traceback.
4. `HISTORY.rst` — an entry recording the behaviour change, since this alters a
   public API's exception behaviour (§5).
5. `README.rst:77` — correct the transaction example (F2), once question 2 is
   answered. In scope because it documents the same method this change is
   about; leaving a known-false example beside a corrected one is worse than
   either alone.

Explicitly out of scope: every other finding in §2. F3, F4, F6, and F7 are
recorded findings, not work items, and they stay findings until somebody
schedules them.

**Why this one.**

- It is the only finding whose intent is written down by a maintainer rather
  than inferred. It needs a confirmation, not a specification.
- Its failure mode is silent by construction (F8). A caller cannot detect it at
  runtime, which ranks it above every other finding per unit of severity.
- The product diff is one line — small enough that the adoption's first ratchet
  run, first characterization test, and first rollback rehearsal all happen on a
  change revertible in one command.
- It repairs the specific mechanism that let a merged fix disappear: a test
  asserting the defect. Leave that test alone and the next attempt at the same
  fix fails the same way.

**Why not the others, briefly.** F3 is the larger problem and probably the more
valuable one, but resolving it needs a backend the fixture does not have, and
its correct next step is a bounded discovery question — not a code change
bundled into this one. F6 is a coverage programme, not a target. F7 is a set of
small independent corrections with no shared decision behind them. Recommending
any two of these together produces a modernization backlog, which is the thing
this workflow exists not to produce.

## 9. What this record does not establish

- That the suite passes. It was not run (§0).
- That F3 is a defect. It is a question, and the only backend under test cannot
  answer it.
- Any requirement for `records` as a product. There is no owner statement and
  no specification; every "intended" behaviour cited above traces to a merged
  PR, the README, or `HISTORY.rst`, and each is named at its use.
- That the verdict in §7 conforms to schema. It was hand-written against the
  field contract (F9).

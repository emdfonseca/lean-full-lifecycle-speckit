# Brownfield Adoption Plan

Repository: `records` (SQL for Humans), GitHub `emdfonseca/pilot-brownfield-records`.
Scope mode: `scan`. Target: none supplied.

Because no target was supplied, this plan covers framework adoption plus a
shallow readiness scan. It does not inventory the estate and does not propose a
modernization backlog.

## 1. Current state

### Product code

| Fact | Evidence |
| --- | --- |
| Single module, 562 lines, no package directory | `records.py`; `setup.py:71` `py_modules=["records"]` |
| Four public classes: `Record`, `RecordCollection`, `Database`, `Connection` | `records.py:25`, `:107`, `:258`, `:350` |
| CLI entry point `records=records:cli` | `setup.py:74`; `records.py:460` |
| Version 0.6.0, SQLAlchemy >= 2.0, ISC licence | `setup.py:56-61` |
| Released to PyPI via `setup.py publish` (twine) | `setup.py:16-51` |

### Tests

| Fact | Evidence |
| --- | --- |
| 31 test functions across 4 files | `tests/test_records.py` (23), `tests/test_transactions.py` (6), `tests/test_69.py` (1), `tests/test_105.py` (1) |
| Only SQLite in-memory is exercised; the file-SQLite and PostgreSQL fixture parameters are commented out | `tests/conftest.py:11-17` |
| No coverage tooling configured anywhere | absence of `.coveragerc`, `pytest.ini`, `[tool.coverage]` |

The suite is a behaviour sample, not a specification. Treat it as evidence of
what the module currently does on SQLite, not as the intended contract for the
PostgreSQL and Redshift extras that `setup.py:78-82` advertises.

### Build, CI, packaging — all preserved

| Mechanism | State | Evidence |
| --- | --- | --- |
| GitHub Actions `pytest` on Python 3.7–3.12 | live, authoritative | `.github/workflows/ci.yml:19` |
| `pip install -r requirements.txt` installs `-e .[pg]` plus pytest | live | `requirements.txt` |
| `tox.ini` targets py27–py36 | stale, still present | `tox.ini:7` |
| `.travis.yml` targets Python 2.7–3.6 | stale, still present | `.travis.yml:3-8` |
| `Makefile` `test`/`init` call `pipenv`, and no `Pipfile` exists | broken, still present | `Makefile:3-5` |
| No Devbox | `devbox.json` absent; `flake.nix` absent |

None of these are changed by this adoption. The stale ones are recorded as
findings and covered by a scoped exception, not deleted. Deleting a build path
during an adoption is the change nobody asked for arriving inside one they did.

### Framework state

| Fact | Evidence |
| --- | --- |
| Spec Kit 1.0.1, Claude integration, Python scripts | `.specify/init-options.json`; `.specify/integration.json` |
| `github-lifecycle` extension installed | `.specify/extensions.yml` |
| `lean-full-lifecycle-governance` preset present on disk | `.specify/presets/lean-full-lifecycle-governance/` |
| Constitution authored, version 1.0.0, no placeholder tokens remain | `.specify/memory/constitution.md:485` |
| GitHub backend is Projects v2, project #4, user-owned | `.specify/github-lifecycle/inspection.json` |
| Only the `Status` field exists; `risk`, `priority`, `severity`, `outcome_status`, `capability` have no field | same file, `notes` |
| `.specify/`, `.claude/`, `.venv-gl/` are untracked; `.gitignore` contains only `.env` | `git status`; `.gitignore` |

`.specify/lifecycle/` holds this plan and `brownfield-discovery.md`. It holds no
`ratchet-baselines.yml`, which the constitution names as the single source for
quality baselines (`.specify/memory/constitution.md`, Principle I) — so no gate
has a recorded baseline yet.

## 2. Quality baseline

Policy names four ratchetable gates
(`.specify/presets/lean-full-lifecycle-governance/policy/quality-gates.yml`).
Their baselines are **not measured in this run, deliberately**: running pytest,
a linter, or a type checker writes `__pycache__/` and `.pytest_cache/` outside
`.specify/`, and `.gitignore` does not cover them. That would turn a scan
somebody agreed to into a change they did not.

The baseline below is therefore structural — what exists, what does not — plus
the exact command that will produce each number at the first ratchet run.

| Gate | Measure | Current tooling | Command to establish the baseline |
| --- | --- | --- | --- |
| `lint_or_static_analysis` | violations, lower is better | none configured | to be chosen at the constitution step; no linter is installed today |
| `type_or_compile_check_when_supported` | errors, lower is better | none; `records.py` carries no annotations | to be chosen at the constitution step |
| `secret_detection` | findings, lower is better | none in-repo; `speckit.github-lifecycle.sensitive` runs inside the workflow | `sensitive.py` over the discovery record |
| `deterministic_change_appropriate_tests` | coverage percent, higher is better | pytest, no coverage plugin | `pytest --cov=records` once `pytest-cov` is a declared dependency |

Recording happens through `ratchet.py --gate <gate> --measurement <n>
--produced-by <command> --write`, writing
`.specify/lifecycle/ratchet-baselines.yml` with `value`, `recorded_at`, and
`produced_by` per entry.

**The first ratchet run reports `baseline_established`, not a pass.** That is
policy (`quality-gates.yml`, `first_run.is_not_a_pass: true`) and it is the
point: a first run that reports green makes every later comparison meaningless.

## 3. Quality ratchet

Rules adopted as written, no local weakening:

1. Every measurable gate holds at its recorded baseline or improves. A
   measurement worse than the baseline is a refusal.
2. The baseline moves only in the improving direction, automatically.
3. Loosening a baseline requires an exception that names the gate
   (`ratchet.loosening.exception_must_name_gate: true`).
4. A gate declared ratcheted with no measure is refused, not skipped.
5. Flaky tests are defects. Disposition is fix, quarantine with an owner and an
   expiry, or remove if invalid.

Adoption sequencing for this repository:

- **At adoption**: record baselines for the two gates that can be measured
  without adding a tool — `secret_detection` (expected 0) and
  `deterministic_change_appropriate_tests` (whatever `pytest --cov=records`
  reports on the SQLite-only suite; expect a modest number, and do not
  improve it in the same change that records it).
- **Blocked until a tool is chosen**: `lint_or_static_analysis` and
  `type_or_compile_check_when_supported`. Choosing a linter and a type checker
  is a stack decision, recorded in the constitution, not invented here.
  Exception EX-002 covers the interval.
- **Never**: retrofitting a baseline from a number nobody produced. An
  unmeasured gate stays unmeasured on the record.

## 4. Scoped exceptions

Each exception below carries the ten fields
`exception-policy.yml` requires. Two fields are unfilled: `owner` and
`approver`. They are real people's names and this plan will not invent them.
`exception.py` refuses an ownerless exception, so **each draft below is refused
until the approver at gate 1 supplies both names.** That refusal is the
mechanism working, not a defect in the plan.

No exception here uses a whole-repository scope, a rule wildcard, or a
one-segment path. None is permanent.

### EX-001 — stale legacy build paths remain unremoved

- `id`: EX-001
- `scope`: `tox.ini`, `.travis.yml`, `Makefile`
- `policy_rule`: `dependency_hygiene`, `build_or_package_validation`
- `reason`: All three target Python versions the project dropped at 0.6.0
  (`HISTORY.rst:1-6`) and `Makefile` calls `pipenv` with no `Pipfile` present.
  Removing them is a change outside an approved target and would destroy the
  only record of how the project used to be built.
- `owner`: _unfilled — supplied at gate 1_
- `approver`: _unfilled — supplied at gate 1_
- `created_at`: 2026-08-24
- `review_or_expiry_at`: 2026-11-24
- `compensating_controls`: `.github/workflows/ci.yml` is the authoritative
  build path and runs on every push and pull request to `master`; the three
  files are not invoked by it.
- `disposition`: active

### EX-002 — no linter and no type checker configured

- `id`: EX-002
- `scope`: `records.py`
- `policy_rule`: `lint_or_static_analysis`,
  `type_or_compile_check_when_supported`
- `reason`: No lint, format, or type configuration exists in the repository.
  The gates cannot produce a number, and picking the tools is a stack decision
  that belongs to the constitution step, not to this plan.
- `owner`: _unfilled — supplied at gate 1_
- `approver`: _unfilled — supplied at gate 1_
- `created_at`: 2026-08-24
- `review_or_expiry_at`: 2026-10-24
- `compensating_controls`: CI executes the suite on six Python versions, which
  catches syntax and import breakage; the module is 562 lines and reviewable in
  one sitting.
- `disposition`: active
- Note: this exception names the two gates it suspends, satisfying
  `exception_must_name_gate`. It suspends measurement, not the requirement —
  when the tools land, the first run establishes a baseline and does not
  report a pass.

### EX-003 — coverage baseline reflects SQLite only

- `id`: EX-003
- `scope`: `tests/conftest.py`
- `policy_rule`: `deterministic_change_appropriate_tests`
- `reason`: The fixture parameterization exercises `sqlite:///:memory:` alone;
  file-backed SQLite and PostgreSQL are commented out (`tests/conftest.py:13-15`)
  while `setup.py:78-82` advertises `pg` and `redshift` extras. Any coverage
  number recorded now describes one backend.
- `owner`: _unfilled — supplied at gate 1_
- `approver`: _unfilled — supplied at gate 1_
- `created_at`: 2026-08-24
- `review_or_expiry_at`: 2026-11-24
- `compensating_controls`: the recorded baseline is annotated with the backend
  it was produced under, so a later PostgreSQL run is compared against its own
  baseline rather than silently against this one.
- `disposition`: active

An expired exception is reported and stops suppressing its rule. It is not
deleted (`exception-policy.yml`, `expiry.on_expiry`).

## 5. Bounded discovery scope

The scan reads. It writes `.specify/lifecycle/brownfield-discovery.md` and
nothing else, and it modifies no file outside `.specify/` — not a format, not a
free-looking lint fix, not a dependency bump.

**In scope**

- `records.py` — public surface of the four classes and `cli()`, the seams
  where behaviour could be characterized, and the transaction and connection
  lifecycle paths.
- `tests/` — what is characterized today and what is not.
- `.github/workflows/ci.yml`, `requirements.txt`, `setup.py` — the live build
  and release path.
- Reconciliation of current behaviour against `README.rst` and `HISTORY.rst` as
  stated intent, flagging where they disagree with the code.
- Test gaps, risk, observability, compatibility, migration, and rollback needs
  for **one** bounded first target.

**Out of scope**

- Any other repository, service, or dependency inventory.
- `examples/randomuser-sqlite.py`, beyond noting whether it still runs.
- Dependency upgrades, reformatting, and rewriting.
- Reverse-specifying the whole module. Code alone is not an authoritative
  requirement, and 562 lines of it is not a spec.

**Output constraint**: the scan recommends exactly one bounded first target. A
scan that recommends five has produced a modernization backlog, which is the
thing this workflow exists not to produce.

## 6. Approvals

| # | Gate | What is being decided | Rejecting means |
| --- | --- | --- | --- |
| 1 | `approve-adoption-plan` | This document, including the owner and approver names for EX-001..003 | adoption aborts; nothing is written beyond this file |
| 2 | `review-discovery` | `brownfield-discovery.md` and its readiness verdict, after the sensitive-data scan and redaction have both reported | discovery is rejected; no target is adopted |
| 3 | `approve-verification-resolution` | How the missing `devbox run verify` is resolved — generated script or overlay | the command stays missing and the first delivery fails at a shell step |

Gate 3 needs a decision now, so it is stated rather than deferred: **there is no
`devbox.json`, so `devbox run verify` and `devbox run release-verify` are both
missing** (`bootstrap-policy.yml:111-114`; `definition_source.file: devbox.json`).
Generating a script requires a recorded stack decision, and none exists. The
recommendation is therefore an **overlay** at
`.specify/lifecycle/verification-overlay.yml` mapping `devbox run verify` to the
command this project already runs — `pytest` — and leaving
`devbox run release-verify` unmapped until a release is actually in scope. The
overlay's project side reaches gate 3 rather than being assumed.

Constitution authoring (`speckit.constitution`) also lands between gates 1 and
2; it is where the linter and type-checker choices behind EX-002 get recorded.

## 7. Validation

Run after adoption, all read-only except where noted:

1. `git status --porcelain` — every modified or added path is under `.specify/`.
   Any other path means the run did something other than what was approved, and
   reporting it as a scan would make the record wrong as well.
2. `git diff --stat HEAD -- . ':!.specify'` — empty.
3. `.github/workflows/ci.yml`, `requirements.txt`, `setup.py`, `tox.ini`,
   `.travis.yml`, `Makefile` are byte-identical to `HEAD`.
4. `speckit.github-lifecycle.doctor` — read-only lifecycle configuration check
   reports usable, matching `inspection.json`.
5. `verify_bootstrap.py --format json` — `present`, `overlaid`, and `missing`
   reported separately. Expect `devbox run verify` overlaid and
   `devbox run release-verify` missing, and expect that to be stated as such
   rather than as resolved.
6. `ratchet.py --gate <each> --format json` — reports
   `baseline_established` for the two measurable gates, and the two gates under
   EX-002 report as excepted with the gate named.
7. `.specify/memory/constitution.md` contains no `[PLACEHOLDER]` tokens.
8. Each exception passes `exception.py` — meaning `owner` and `approver` are
   real names, not `team`, `tbd`, or a dash.
9. `sensitive.py` over `brownfield-discovery.md` reports zero findings after
   redaction, and reports `patterns_from_policy: true`. If it is false, the
   preset is not wired and a fallback ran; that is stated, not reported clean.
10. The discovery record names every file the run wrote.

Adoption is validated only when 1–10 all hold. A partial pass is a partial
adoption and is reported as one.

## 8. Rollback

Nothing tracked by git is modified, so rollback does not touch the working tree
of the product.

| Step | Command | Effect |
| --- | --- | --- |
| 1 | `git status --porcelain -- . ':!.specify' ':!.claude'` | confirm there is nothing outside the framework to revert; if this is non-empty, stop and revert those paths individually with `git checkout --` before continuing |
| 2 | `rm -rf .specify/lifecycle` | removes this plan, the discovery record, the ratchet baselines, the verification overlay, and the adoption report |
| 3 | `git checkout -- .specify/memory/constitution.md`, or restore the template from `.specify/templates/constitution-template.md` if the file is untracked | returns the constitution to its pre-adoption state |
| 4 | leave `.specify/` and `.claude/` in place, or remove them wholesale for a full framework removal | Spec Kit itself is untracked, so removal is a directory delete and loses nothing tracked |

Not rolled back automatically: the GitHub project board (#4) and any issue
created under it. These are outside the working tree and outside this run's
writes; if the adoption is abandoned, close them by hand.

The steps are ordered. Step 1 before step 2 — if a file outside `.specify/` was
touched, deleting the record of what this run did removes the only evidence of
which file that was.

## 9. Next action

Approve or reject this plan at gate 1, supplying the `owner` and `approver`
names for EX-001, EX-002, and EX-003. Until those names exist, all three
exceptions are refused and the ratchet has no sanctioned way to start.

# Brownfield Adoption Report

Repository: `records` (SQL for Humans). Run `87a9ac4d`, workflow
`lifecycle-brownfield-adoption`, step `validate-adoption`.
Scope mode: `scan`. Target: none supplied.

Verdict: **partial adoption**. The tree is clean and every build path is
preserved. The governance mechanisms the plan promised — exception records and
ratchet baselines — do not exist on disk, so nothing is yet enforced.

Adoption is validated only when all ten checks in
`brownfield-adoption-plan.md` §7 hold. Six hold, four do not.

## 1. Actual state

### Working tree — clean

| Check | Result | Evidence |
| --- | --- | --- |
| §7.1 `git status --porcelain` | **pass** — only `?? .claude/` and `?? .specify/` | nothing outside the framework is added or modified |
| §7.2 `git diff --stat HEAD -- . ':!.specify'` | **pass** — empty | no tracked file changed |

`.venv-gl/` sits at the repository root and is invisible to `git status`
because `venv` wrote `.venv-gl/.gitignore` containing `*`. It is self-ignoring,
not ignored by this repository — the repository's own `.gitignore` still
contains only `.env`.

### Framework state

| Fact | Evidence |
| --- | --- |
| Constitution v1.0.0, ratified 2026-08-24, no placeholder tokens (§7.7 **pass**) | `.specify/memory/constitution.md:485` |
| Stack decision recorded: Ruff, and mypy non-strict on `records.py` only | `.specify/memory/constitution.md:239`, `:244` |
| All three gates recorded `choice: approve` | `.specify/workflows/runs/87a9ac4d/state.json` |
| `lifecycle/` holds three files: the plan, the discovery record, the verification-commands report | `ls .specify/lifecycle/` |
| No `ratchet-baselines.yml`, no `verification-overlay.yml`, no exception record anywhere | `find .specify -iname '*exception*'` returns only the policy file |
| Discovery names the one file it wrote (§7.10 **pass**) | `brownfield-discovery.md:10` |

### Discovery accuracy — spot-checked and correct

Finding F1 was verified against the code and history rather than taken on
trust. `records.py:344-345` has `except: tx.rollback()` with no `raise`.
Commit `a1ebdde` added that `raise`; `5df61d3` ("fix earlier commit") removed
it again. `tests/test_transactions.py:57-63` asserts *after* the `with` block,
which only executes when the exception is swallowed — the test encodes the
defect. The readiness verdict is `not_ready`, and §8 recommends exactly one
bounded target, as the workflow requires.

### GitHub state — two discrepancies

| Item | Recorded | Actual |
| --- | --- | --- |
| Repository resolved by bare `gh` | `emdfonseca/pilot-brownfield-records` (`github-lifecycle-config.yml:3`) | `kennethreitz/records` — `gh repo set-default --view` resolves to the `upstream` remote |
| `project_number` | `4` (`inspection.json`) | `null` in `github-lifecycle-config.yml:4` |

Neither blocks today. Lifecycle scripts take an explicit `--repo`, and
`config.py:116` falls back to auto-selecting the project when
`project_number` is null. Both are latent: a bare `gh` write in this checkout
targets a third party's repository, and an unpinned project number resolves by
discovery rather than by declaration.

`doctor.py` reports `usable: true`, `config_source: scaffolded`, backend
`projects-v2`, `Status` as the only role-bearing field — matching
`inspection.json`. §7.4 **passes** on substance; its `repository` line reflects
the `gh` default above, not the configured repository.

## 2. Quality ratchet — not started

`quality-gates.yml` sets `ratchet.baseline_file:
.specify/lifecycle/ratchet-baselines.yml`. **That file does not exist.**
Zero of four measurable gates have a baseline.

§7.6 does not hold, and for two separate reasons:

1. **The command as written is unrunnable.** `ratchet.py --gate <g> --format
   json` exits with `one of --measurement or --loosen-to is required`. A
   measurement must be supplied; there is no read-only status mode.
2. **`ratchet.py` cannot report a gate as excepted.** `assess()`
   (`scripts/ratchet.py:114`) takes no exception parameter. Only `loosen()`
   (`:173`) does. Supplying any measurement for an EX-002 gate returns
   `baseline_established` and records it — confirmed by a dry run of
   `lint_or_static_analysis`, which happily accepted a baseline for a gate the
   plan says is suspended. The plan's expectation that "the two gates under
   EX-002 report as excepted with the gate named" describes behaviour the tool
   does not have.

What the tool does do correctly: a dry `--measurement 0` on `secret_detection`
returned `"verdict": "baseline_established", "passed": false`, with the message
"This is a baseline, not a pass: nothing has been compared yet." First-run
semantics work as policy specifies.

One consequence worth acting on: **EX-002's stated reason is now stale.** It
suspends lint and type gates because "picking the tools is a stack decision
that belongs to the constitution step". The constitution has since picked them
— Ruff and mypy non-strict. The blocker EX-002 describes no longer exists; what
remains is installing the tools, which is a different reason with a different
expiry.

## 3. Scoped exceptions — none exist as records

EX-001, EX-002, and EX-003 appear as prose in
`brownfield-adoption-plan.md` §4, and are cited in
`constitution.md:451-453`. They exist nowhere else. §7.8 does not hold: there
is no record for `exception.py` to read, so no exception has ever been
validated and none suppresses any rule.

Gate 1 (`approve-adoption-plan`) recorded `choice: approve`. Its stated
condition — supplying `owner` and `approver` for all three — was never met.
All three still read `_unfilled — supplied at gate 1_`. The gate passed; its
precondition did not.

Running `exception.py` against EX-001 exactly as the plan drafts it returns
`"accepted": false` with four refusals:

- `owner` present but empty
- `approver` present but empty
- scope `['tox.ini', '.travis.yml', 'Makefile']` "covers a directory tree from
  too near the root to be a scope"
- that scope "is a glob and records no `baseline`"

The last two are structural, not a matter of filling in names: **a multi-path
list is not a valid scope.** EX-001 must be split into one record per file.

Verified by construction: with real `owner`/`approver` names and a single-path
scope, all three exceptions return `"accepted": true, "suppresses_rule": true`
with zero refusals. `EX-001` → `tox.ini` (plus two siblings), `EX-002` →
`records.py`, `EX-003` → `tests/conftest.py`. Nothing else needs to change.

## 4. Preserved build paths — fully preserved

§7.3 **passes**. Every file is byte-identical to `HEAD`, confirmed by
`git hash-object` against `git rev-parse HEAD:<path>`:

`.github/workflows/ci.yml`, `requirements.txt`, `setup.py`, `tox.ini`,
`.travis.yml`, `Makefile`, `records.py`, `tests/conftest.py`, `.gitignore`.

The three stale paths — `tox.ini` (py27–py36), `.travis.yml` (2.7–3.6),
`Makefile` (calls `pipenv` with no `Pipfile`) — are still present and still
unremoved, which is what EX-001 exists to record. The authoritative path,
`.github/workflows/ci.yml`, is untouched.

### Verification commands — reported honestly, resolution not applied

`verify_bootstrap.py --path . --format json` returns:

```
{"present": [], "missing": ["devbox run verify", "devbox run release-verify"],
 "overlaid": [], "problems": [], "wrote": [], "resolved": false}
```

§7.5 **passes** as a reporting check: `present`, `overlaid`, and `missing` are
reported separately, and the state is stated as unresolved rather than as
resolved. But gate 3 recorded `choice: approve` for Route A, and
`verification-overlay.yml` was never written. The resolution is approved and
unapplied — every workflow that shells out still fails at its first delivery.

## 5. Absence of unrelated changes — confirmed

No tracked file was modified, added, or deleted. No formatting, no dependency
bump, no deletion of a stale build path. The scan wrote inside `.specify/` and
nowhere else, and the discovery record names the single file it produced. This
is the check the workflow exists to protect, and it holds without qualification.

## 6. Checks that did not hold

| Check | Status | Why |
| --- | --- | --- |
| §7.6 ratchet | **fail** | no `ratchet-baselines.yml`; command unrunnable as written; `assess()` cannot report an exception |
| §7.8 exceptions | **fail** | no exception record exists; EX-001's list scope is refused independently of the missing names |
| §7.9 sensitive scan | **fail** | `sensitive.py --record brownfield-discovery.md` raises an unhandled `yaml.scanner.ScannerError` — it expects a YAML/JSON record, not Markdown. No finding count and no `patterns_from_policy` flag was ever produced. The workflow's `scan-evidence-for-sensitive-data` and `redact-evidence-before-review` steps both recorded `exit_code: 0` with empty `stdout` and `dispatched: true`, meaning they were handed to the agent, not executed with a captured result. Per the plan's own rule, this is stated rather than reported clean. |
| Readiness verdict | **unvalidated** | discovery F9 is correct, and understates it: `jsonschema` is absent from `.venv-gl` **and** `readiness-verdict.schema.json` does not exist anywhere in `.specify/`. Two blockers, not one. The `not_ready` verdict is hand-written. |

## 7. Next action

Fill `owner` and `approver` with real names on EX-001, EX-002, and EX-003, and
write them to `.specify/lifecycle/exceptions/` as one validated record per
scope path — `tox.ini`, `.travis.yml`, and `Makefile` as three separate EX-001
records, since `exception.py` refuses the plan's combined list scope — then
confirm each returns `"accepted": true` under
`exception.py --record <file> --policy-root .`.

Everything else waits on this. The ratchet cannot record a baseline for a gate
whose exception does not exist, and until then no gate is enforced and no
exception is in force.

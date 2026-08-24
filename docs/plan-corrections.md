<!-- The corrected phase sequence and the reasoning behind it. Written
before P0b and kept because the resequencing it argues for is not
derivable from the roadmap alone: catalog mechanics moved from P14 to
P0c, the adapter core moved ahead of the workflows that consume it, and
OpenCode bootstrap moved last because its role mappings need pilots. -->

# Plan: correct the roadmap, then implement to Spec Kit bundle 1.0.0

## Context

`speckit-lifecycle` is a GitHub Spec Kit **bundle** (`bundle.yml`, id `lean-full-lifecycle`, v0.1.0)
shipping 1 governance preset, 1 GitHub extension, and 7 lifecycle workflows.
`docs/implementation-roadmap.md` defines Phases 0–11 to reach a supported 1.0.0.

The roadmap is a good requirements document and a weak plan. Three problems make
executing it as written wasteful:

1. **It has never touched a real CLI.** `VALIDATION.md:41-47` states `specify bundle
   validate`, `bundle build`, and `smoke_test.py` have never run, and none of
   `specify`/`devbox`/`gh`/`opencode` are installed. Yet roadmap line 3 calls 0.1.0
   "pilot-ready". Every composition claim in the repo is asserted, not verified.
2. **It targets a stale Spec Kit.** Upstream is **v1.0.1 (2026-08-21)**; the repo pins
   `>=0.16.5` in 16+ places. v1.0.1 tightened manifest validation. No phase tracks
   upstream compatibility.
3. **It ignores the repo's own tooling.** `validate_source.py`, `build_release.py`,
   `install_dev.py`, `smoke_test.py`, `tests/`, CI, `Makefile`, `catalogs/`, `dist/`,
   and six of seven `docs/*.md` are never mentioned. Adding one workflow today means
   editing five uncoordinated hardcoded lists. Doing that eight times is the plan's
   real cost.

4. **The artifact is not a container.** P0a established (`docs/evidence/substrate-1.0.1.md`,
   defect D7) that `specify bundle install` never reads the components out of a bundle
   zip. `bundler/services/primitives.py` offers each component exactly two install
   sources: an asset shipped inside the Spec Kit CLI, or a catalog download. A bundle is
   a *manifest of references*. Nothing about this bundle can be installed, updated, or
   removed until its components are reachable from a catalog.

Outcome: a corrected, risk-ordered sequence that puts the cheapest invalidating check
first, treats catalog mechanics as foundational test infrastructure rather than release
polish, fixes the multi-source-of-truth problem before scaling to 15 workflows, and
keeps the roadmap's substance intact.

---

## Corrected phase sequence

| New | Phase | Delivers | Old |
|---|---|---|---|
| **P0a** | Substrate reality check | **DONE** — H1–H9 verdicts, 7 defects, version evidence | new |
| **P0b** | Conformance fixes + bundle-root relocation | pin raised; D1 fixed; dev files moved out of the bundle dir | new |
| **P0c** | Catalog harness + artifact pipeline | per-component zips + `file://` catalog; install/update/remove green | new |
| **P0d** | Tooling ownership + single source of truth | `bundle.yml` and catalogs derived; validator/tests/CI rewritten | new |
| **P0e** | Doc truth pass | false claims removed; GitHub App ADR | new |
| **P1** | Requirements + traceability | `tooling/requirements/`, coverage gate in CI | Phase 0 |
| **P2** | Reproducible environment | devbox **or** Make — one, not both | Phase 1 (env) |
| **P3** | GitHub adapter core | `github_api.py`, inspect/plan/transition, read-back, audit | Phase 6 (part) |
| **P4** | Vertical slice: `lifecycle-refine` | readiness schema → gate → deterministic transition | Phase 2 (part) |
| **P5** | Decompose + relationships + capture/dedupe | `lifecycle-decompose`; wires `capture`/`link` | Phase 2 + 6 |
| **P6** | Triage + discover | `lifecycle-triage`, `lifecycle-discover` | Phase 2 |
| **P7** | Uncertainty resolution | `lifecycle-prototype`, `lifecycle-spike`, threat branch | Phase 3 |
| **P8** | Outcome review | `lifecycle-outcome-review` (parallel with P7) | Phase 4 |
| **P9** | Greenfield/brownfield hardening | mismatch gate, verify-command bootstrap | Phase 7 |
| **P10** | Monorepo / worktree / parallel teams | context targeting, overlay survival | Phase 8 |
| **P11** | OpenCode agent bootstrap | model resolution, role agents, permission tests | Phase 5 |
| **P12** | Acceptance suite | full matrix incl. bundle mechanics | Phase 9 |
| **P13** | Controlled pilots | 4 pilot streams + metrics | Phase 10 |
| **P14** | Publish 1.0.0 | catalog *publication* only — real URLs, releases, checksums, support policy | Phase 11 |

Four structural changes:

- **Catalog mechanics move from P14 to P0c.** D7 makes a reachable catalog the precondition
  for `bundle install`/`update`/`remove`/`info`, so it is test infrastructure, not release
  polish. Only publication stays at P14. This is the largest reordering in the plan and the
  one the original roadmap got most wrong: its Phase 1 exit gate demands an install lifecycle
  that its Phase 11 makes possible.

- **Phase 6 splits.** Its transition core becomes P3, *before* the first workflow that
  consumes it. This resolves the roadmap's own contradiction: its recommended first slice
  (`docs/implementation-roadmap.md:1120-1141`) is `lifecycle-refine` → deterministic
  adapter → read-back, but the adapter sat four phases later.
- **Phase 5 (OpenCode) demotes to P11.** `policy/model-routing.yml` is entirely
  null-valued; the correct role set is unknowable until pilots run.
- **Old Phase 0 (traceability) demotes one slot to P1.** Requirements written against an
  unproven substrate encode wrong requirements.

---

## P0a — Substrate reality check — **DONE**

Executed 2026-08-23 against `specify` 1.0.1. Full record in
`docs/evidence/substrate-1.0.1.md`; baseline commit `b700f30`, evidence commit `892309e`.

**Verdicts:** H1 passes offline / fails online (D6); H2, H3, H4, H6, H7, H9 pass;
H5 partial (D7); H8 not tested, deferred to P11.

**H7 — the design-critical hypothesis — passes.** The composition chain is
`[base] lean v1.0.0` → `[append] lean-full-lifecycle-governance v0.1.0`, and the CLI
confirms "lower priority number = higher precedence". The repo's 20/replace + 10/append
configuration is correct as authored. `lean` supplies a base for only 5 of the 9 addended
commands; for `clarify`, `checklist`, `analyze`, and `converge` the **core Spec Kit
template** is the base and composition still resolves correctly.

No manifest required any change to validate on 1.0.1, so raising the pin carries no
migration cost.

**Seven defects, carried into the phases below:**

| ID | Defect | Owner phase |
|---|---|---|
| D1 | Extension config target `name: github-lifecycle` never scaffolds | P0b |
| D2 | `bundle build` packages the entire repo (123 files, incl. `dist/`, `scripts/`, `tests/`) | P0b |
| D3 | ~~`build_release.py` superseded~~ — **retracted**, see below | P0c |
| D4 | `bundle info` requires a catalog; fails for a locally installed bundle | P0c |
| D5 | `--dev` installs then `bundle install` records 0 components; `remove` is a no-op | P0c |
| D6 | Online `bundle validate` can never pass from a source checkout | P0d |
| D7 | A bundle artifact is not self-contained; catalogs gate all install testing | P0c |

**D3 is retracted.** `specify bundle build` produces one bundle-level zip that is inert
for installation. A catalog serves **per-component** zips — `catalog.download_extension(id)`
fetches one archive per component and hands it to `install_from_zip`. There is no official
per-component packaging command (`specify preset|extension|workflow --help` show none), so
producing those artifacts is our responsibility, and `scripts/build_release.py`'s
per-component output is the required shape, not superseded work. Its existing zips are flat
with the manifest at root, matching the `--dev` directory layout; P0c verifies they install.

---

## P0b — Conformance fixes and bundle-root relocation

Small, mechanical, and a prerequisite for the artifact pipeline.

**Raise the pin to `>=1.0.1,<2.0.0`.** P0a proved zero migration cost. `>=0.16.5` is
unbounded and already claims compatibility across a major boundary it was never tested
against. The pin currently lives in `bundle.yml:15`, `preset.yml`, `extension.yml`, 7×
`workflow.yml`, 4× `catalogs/*.json`, and prose in `README.md`, `VALIDATION.md:47`,
`INSTALL-LOCAL.md`, `docs/installation.md`. Sweep by hand now; P0d makes it one declared
value with a consistency check.

**Fix D1.** `components/extensions/github-lifecycle/extension.yml`:
`config[0].name: github-lifecycle` → `github-lifecycle-config.yml`.
`ExtensionManager._target_follows_preserved_convention` requires a top-level target ending
in `-config.yml` or `-config.local.yml`; anything else is rejected because
`remove(keep_config)` would not preserve it. The current value means the extension's config
has never scaffolded on any install, and `scripts/doctor.py`'s config lookup has always read
a file that does not exist. Verify by re-running `specify extension add --dev` and
confirming `.specify/extensions/github-lifecycle/github-lifecycle-config.yml` appears.

**Relocate the bundle root (D2).** `packager.EXCLUDE_NAMES` is exactly
`{".git", "__pycache__", ".DS_Store"}` and there is **no `.bundleignore`** — grep of
`packager.py` returns nothing. Whatever sits in the bundle directory ships. The build
already embedded `dist/` (including all 10 stale component zips), `scripts/`, `tests/`,
`.github/`, `.claude/`, and a `.specify/` cache created by the validate run itself.

Move the shipped surface into `bundle/`:

```
bundle/            bundle.yml, README.md, components/, policy/
scripts/ tests/ tooling/ docs/ catalogs/ dist/ .github/    <- stay at repo root, never shipped
```

Build becomes `specify bundle build --path bundle/ --output dist/`. This is the only
mechanism the CLI offers, it makes the command honest about what is being packaged, and it
removes the need for the `tests/test_packaging.py` exclusion assertion the plan previously
relied on (keep the test anyway as a regression guard). Add `.specify/` to `.gitignore`
— already done.

Settle this before P0c, because the artifact pipeline and every generator path key off the
bundle root.

**Open question for this phase:** root `policy/` is byte-identical to the preset's copy, but
only the preset copy installs (the composed `speckit.converge` references
`.specify/presets/lean-full-lifecycle-governance/policy/`). Since the bundle zip is inert,
the root copy never reaches a user. Determine whether it is source-only convenience and, if
so, whether the byte-equality invariant is still worth enforcing.

---

## P0c — Catalog harness and artifact pipeline

**The phase D7 forces into existence.** Previously this work sat in P14 as "publish
catalogs". It is not release polish: it is the test fixture every install-dependent phase
depends on. Until it exists, `bundle install`, `update`, `remove`, and `info` cannot be
exercised at all, and no phase from P3 onward can prove its exit gate end-to-end.

Split the concern the old plan conflated:

| Concern | Phase | Content |
|---|---|---|
| Catalog **mechanics** | **P0c** | per-component zips, catalog JSON, `file://` source, full install lifecycle |
| Catalog **publication** | P14 | real URLs, `YOUR-ORG` replaced, GitHub releases, checksums, provenance, support policy |

### Deliverables

1. **Per-component artifact build.** Rehabilitate `scripts/build_release.py` (do not delete
   it — D3 retracted): one zip per preset, extension, and workflow, plus the bundle-level
   zip from `specify bundle build --path bundle/`. Drop the hardcoded `VERSION = "0.1.0"`
   (`:22`) in favour of the manifest value.
2. **Catalog generation.** `scripts/generate_catalogs.py` emits the four
   `catalogs/*.json` with `download_url` parameterised by a catalog root, so the same
   generator serves `file://<abs path>/dist/` locally and the published base URL at P14.
   This is what makes the `YOUR-ORG` placeholder a *parameter* rather than a defect.
3. **Local catalog wiring.** `specify bundle catalog add file://…` —
   `bundler/commands_impl/catalog_config._is_local_path` accepts `file://`, `http(s)://`,
   `builtin://`, and bare local paths, so no network or hosting is needed.
4. **A reusable test fixture** that stands the whole thing up in a tmp dir: build → generate
   → `catalog add` → `specify init` → `bundle install`. Every later phase's sandbox test
   consumes this.

### Exit gate — the lifecycle the roadmap always claimed and never had

In a clean repo, installing **only** via the catalog (no `--dev` adds):

- [ ] `bundle install lean-full-lifecycle` succeeds and `bundle list` reports **10 components**, not 0 (D5)
- [ ] `bundle info lean-full-lifecycle` resolves (D4)
- [ ] second install is idempotent
- [ ] `bundle update` succeeds
- [ ] `bundle remove` actually uninstalls the components it installed, and leaves components other bundles reference
- [ ] reinstall succeeds
- [ ] `specify preset list` after install shows lean at 20 and governance at 10, and `preset resolve speckit.specify` shows the two-layer chain

D5 is the diagnostic: the run that produced "0 components" had installed everything with
`--dev` first, so the bundle owned nothing. A catalog-only install is what attributes
components to the bundle and makes `remove` meaningful.

### Consequence for `install_dev.py`

Its per-component `--dev` adds are currently the *only* working local install path, which is
why the script exists. Once the local catalog works, it is superseded as the primary dev
loop and should be reduced to a thin wrapper over the harness, or deleted. Decide in P0d.

---

## P0d — Single source of truth and tooling ownership

The root cause of the plan's cost. Five files each hold a partial copy of "what components
exist"; nothing checks agreement.

**SoT = the component manifests on disk**, plus one new metadata file. Do *not* add extra
keys to `bundle.yml` — 1.0.1 tightened manifest validation, and catalogs need fields
(`download_url`, `provides` counts, `updated_at`) with no place in the bundle schema.

| Artifact | Role |
|---|---|
| `components/**/{workflow,preset,extension}.yml`, `policy/*.yml` | authoritative, hand-authored |
| `tooling/bundle-meta.yml` (new) | authoritative: org slug, repo/catalog URLs, release-tag pattern, `speckit_version` pin, version |
| `bundle.yml` | derived, committed — `scripts/generate_manifests.py` |
| `catalogs/*.json` | derived, committed — `scripts/generate_catalogs.py` |
| `install_dev.py` workflow list, `build_release.py` VERSION, `tests/` | derived at runtime |

New shared loader `scripts/lib/inventory.py` exposes `load_inventory() -> Inventory` with
`Component(kind, id, ref, version, path, manifest, commands)`; `ref` (`workflow:lifecycle-refine`)
is also the traceability key used in P1. The three hardcoded command sets at
`validate_source.py:29-48,252-262` are replaced by `inventory.core_commands()` /
`extension_commands()`, and the check **inverts**: from "is this the list I expect" to "does
every workflow step reference a command some component actually provides".

### Validator refactor

Restructure `scripts/validate_source.py` (596 lines, target well under 200) around a check
registry in `scripts/lib/registry.py`: `Check(id, title, scope, severity,
strict_publish_only, fn)` yielding `Finding(check_id, severity, subject, message)`. Check ID
families: `STRUCT-*` (delegable), `INV-*` (bundle invariants), `SEC-*`, `PUB-*`.

| Existing check | Action |
|---|---|
| semver/id format, required fields, file-ref existence | **delegate** to `specify bundle validate` |
| description < 100 chars (`:277`) | **delete** — official schema says 200; rule is arbitrary |
| preset list literal (`:127`), 9 core / 6 extension command literals | **delete** — derive from manifests |
| priority 20/replace + 10/append (`:139-149`) | **keep, generalise** — drive from `bundle-meta.yml` |
| exactly one extension (`:151-158`) | **keep** — a stated packaging decision |
| bundle workflow refs == disk dirs (`:160-173`) | **replace** with a regeneration-diff check |
| 10 required policy filenames (`:50-61`) | **generalise** — glob, assert preset copy is the identical *set* |
| policy byte-equality (`:217`) | **keep** unmodified |
| config-template safety defaults (`:311-328`) | **keep**, move key list to `tooling/invariants.yml` |
| gate verdict declared + `""` in enum (`:451-463`) | **keep** |
| no `{{ }}` in `shell.run` (`:465-471`) | **keep, hardcoded** — injection invariant |
| shell allowlist (`:24-27`) | **keep as data** → `tooling/invariants.yml: allowed_shell` |
| transition contract (`:338-407`) | **keep, generalise** — see below |
| `YOUR-ORG` scan | **keep**, drives `--strict-publish` |

The transition contract currently regex-scrapes `"Approved plan:"` / `"Write exactly …md"`
from free prose — fragile once eight new workflows are written. Generalise on two axes:
which commands need it moves to `tooling/invariants.yml` (`write_effect_commands`,
`plan_command`); how pairing is proven moves from prose regex to a **slug convention** —
step `transition-output-done` must be preceded by a plan step whose args contain
`…-output-done.md` and by a gate. Prose regexes survive only as presence assertions.

New checks that become free: every write-effect step is preceded by a `type: gate` with no
intervening write-effect step; every `command:` resolves to a provided command; every gate's
`show_file` is produced by an earlier step.

New CLI flags: `--only <CHECK_ID>` (negative fixtures), `--scope`, `--format json`, and
`--list-checks --json` — the last is what makes checks addressable from `requirements.yml`
as `check:INV-SHELL-ALLOWLIST`.

### Test layer

Delete `tests/test_bundle_source.py` tests 2–6 (`:27-132`). Each re-implements a validator
check, and `test_transition_commands_have_prior_plans_and_gates` (`:82`) is strictly
*weaker* — it omits the plan-path match, so it passes on a bundle the validator rejects.

**Switch to pytest.** Decisive reason: the bidirectional traceability check in P1 needs test
metadata (`@pytest.mark.req(...)`) and `--collect-only` introspection, which `unittest` does
not provide. Also gives native parametrisation over 15 workflows, `requires_specify` markers,
`tmp_path`, and `--junitxml` for release evidence. Add `pytest`, `jsonschema` to
`requirements-dev.txt` (currently one line) and a minimal `pyproject.toml`.

| File | Kind |
|---|---|
| `tests/test_check_negatives.py` | negative fixtures — `tests/fixtures/negative/<CHECK_ID>/<case>.yml`; parametrised over `REGISTRY`, fails if any check has no fixture. **Tests that checks can fail — the current suite does not.** |
| `tests/test_schemas.py` | every `components/**/*.yml` × `tooling/schemas/*.schema.json` |
| `tests/test_generated_artifacts.py` | `generate_* --check` byte-identical |
| `tests/test_packaging.py` | built zip contains no `tooling/`, `tests/`, `dist/`, `.github/` |
| `tests/test_workflow_parity.py` | P7 drift control (below) |
| `tests/sandbox/test_lifecycle.py` | `@pytest.mark.requires_specify` — install/list/info/second-install/update/remove/reinstall |
| `components/extensions/github-lifecycle/tests/` | P3 fixture/replay tests, excluded from the shipped extension via `.extensionignore` |

### Owner assignments for the currently-unowned layer

| Asset | Action |
|---|---|
| `scripts/build_release.py` | **kept** (D3 retracted) — rehabilitated in P0c as the per-component artifact builder; `VERSION = "0.1.0"` (`:22`) replaced by the manifest value |
| `scripts/install_dev.py` | delete the 7-id list (`:17-26`); resolve the **double-install defect** — its manual `--dev` adds (`:117-165`) followed by `bundle install` (`:177`) are exactly what produced D5's "0 components". Once P0c's catalog harness works this path is superseded: reduce to a wrapper or delete |
| `scripts/smoke_test.py` | today it never runs `bundle validate` or `bundle build` — the packaging path is unexercised even by the smoke test. Add validate → build → install-from-artifact → update → remove → reinstall |
| `dist/` | already removed from VCS and `dist/.gitkeep` created (both done alongside P0a). Now also the local catalog's serving root |
| `catalogs/*.json` | generated in P0c with a parameterised catalog root; CI blocks publish while the root is still a placeholder |
| YAML dumping | use `ignore_aliases = lambda self, data: True` plus pinned `sort_keys=False, width=100` — the `&id001` anchors are a round-trip artifact and would produce spurious diffs in any byte-compared output. Fix in the same PR as `generate_manifests.py` |
| `docs/*.md` | P0d corrects; thereafter every phase exit gate gains "affected docs updated" — that is the durable anti-rot mechanism |

---

## P0e — Doc truth pass

**Resolve the GitHub App contradiction by dropping the App.** `docs/security.md:15-16`
("not a privileged daemon or hosted service") and `PACKAGING-DECISIONS.md:47-55` both already
say no; the App (roadmap:657,748,1104) is the newest and least-justified claim. It is a
registered identity with a private key, token lifecycle, and org-admin approval path — a
hosted product, where this bundle ships zips. Nothing in the acceptance suite needs one:
Issue Fields, sub-issues, dependencies, rate-limit handling, and read-back are all reachable
with `gh` + a fine-grained PAT locally and `GITHUB_TOKEN` in CI. Least privilege is achieved
exactly as `security.md` already prescribes — separate the schema-admin credential from the
value-transition credential. Record the deferral as an ADR.

Also correct: roadmap:3 "pilot-ready"; `INSTALL-LOCAL.md:18-19`, which unzips
`lean-full-lifecycle-speckit-0.1.0-source.zip` and `cd`s into a directory neither of which
`build_release.py` produces (it emits `lean-full-lifecycle-local-source-0.1.0.zip`, zipped
flat); `docs/publishing.md:45`, which tells you to upload that inspection-only artifact as a
release asset while `VALIDATION.md:60-63` says it is not installable; and the duplicate,
drifted install sequences in `docs/installation.md:28-35` vs `INSTALL-LOCAL.md:45-53`.

---

## P1 — Requirements and traceability (was Phase 0)

Cut the roadmap's nine files to three. `tooling/requirements/requirements.yml`,
`tooling/schemas/requirements.schema.json`, `scripts/validate_requirements.py`.

| Roadmap deliverable | Verdict |
|---|---|
| `traceability.yml` | **drop** — a second place to forget to update, the exact failure mode the system exists to prevent. Put `components:`/`verified_by:` on the requirement |
| `acceptance-scenarios.yml` | **drop** — acceptance scenarios *are* tests; scenario prose belongs in the test docstring |
| `release-gates.yml` | **drop** — derive: every `must` with `release <= X` has `status: verified`. One `gates:` key for non-derivable gates (pilot sign-off) |
| `generate_coverage_report.py` | **drop** — `validate_requirements.py --report md\|json` |

Requirement record: `id`, `statement`, `priority` (must/should/may), `owner`, `release`
(mandatory — undated requirements are wishes), `status` (planned/implemented/verified/withdrawn),
`components` (refs), `verified_by` (pytest node ids), `evidence`.

Link resolution, all machine-checkable: `workflow:`/`preset:`/`extension:` → `inventory.by_ref()`;
`command:` → provided-command set; `policy:` → `policy/*.yml`; `check:` → `--list-checks --json`;
`verified_by` → `pytest --collect-only -q`.

**The anti-rot device is bidirectionality.** Tests carry `@pytest.mark.req("REQ-…")`;
`validate_requirements.py` diffs both directions and errors when a requirement names a test
that does not claim it, or a test claims a requirement that does not list it. You cannot add
a YAML entry without touching the test, and the YAML cannot rot away from the suite. Without
this the system is write-only bureaucracy.

Start with ~9 families covering work in flight, not the roadmap's 18; an explicit `families:`
allowlist makes each addition deliberate. Of the 7 CI rules, keep four, subsume two into node-id
resolution, and drop "deprecated requirement removed without migration record" (needs ADR
infrastructure that does not exist) in favour of `status: withdrawn` requiring `superseded_by:`
or `rationale:`. Gate reverse coverage (component without a requirement) at the release tag
only — as a per-PR error it is where paperwork accumulates.

**Placement: `tooling/` at the repo root, outside `bundle/`.** P0a settled the open question:
there is no `.bundleignore`, and `bundle build` packages everything under the bundle directory.
The P0b relocation is what protects `tooling/` — it sits beside `bundle/`, not inside it, so it
is structurally unshippable rather than ignored. `schemas/` is also a conventional
*component-internal* name (roadmap:672 puts one inside the extension), so keeping ours under
`tooling/` avoids a collision if Spec Kit later reserves the root name. Retain
`tests/test_packaging.py` asserting no built-zip entry starts with `tooling/`, `tests/`,
`dist/`, or `.github/` — now a regression guard on the relocation rather than the primary
defence.

---

## P2 — Environment

Pick **one**. `devbox run validate/test/build/smoke` (roadmap:203-207) duplicates
`Makefile:1-13` one-for-one and the roadmap never says whether Make survives. Recommend devbox
delegating to make, or delete the Makefile. Note Devbox is already assumed as a *target-product*
dependency (`README.md:77`, `policy/framework.yml:5`, and 5 of 7 workflows' shell steps run
`devbox run verify`) — that is a separate concern from source-repo tooling and both must be stated.

---

## P3–P8 — Feature phases

Substance is unchanged from the roadmap; only the order and the pairing change.

- **P3 GitHub adapter core** — `components/extensions/github-lifecycle/scripts/{github_api,inspect,plan,transition}.py` plus `schemas/`, `fixtures/`, `tests/`. Today only `doctor.py` exists (56 lines: `gh auth status` + `gh repo view`) and the other five commands are prose instructions to an agent. Fixture/replay tests with an injectable transport, zero network: field/option ID resolution, duplicate Project-local field, pagination, 403 secondary rate limit → backoff, partial write → read-back mismatch, idempotent re-link, `Output Done` never inferred from issue closure.
- **P4 `lifecycle-refine`** — the roadmap's own best first slice (`:1120-1141`), now actually buildable. Proves: new workflow + schema validation + human gate + extension + Issue Fields + deterministic mutation + read-back.
- **P5** adds `relationships.py`, `capture.py`, `deduplicate.py` and `lifecycle-decompose` together — decompose is meaningless without native hierarchy. **This is also where `capture` and `link` get wired or deleted: both are shipped extension commands used by zero workflows today.** Reassess against upstream `speckit.taskstoissues` (H9).
- **P7** — 1.0.1 requires a `cases` block on `switch` steps; author `uncertainty_mode` accordingly.
- **P8** is independent of P7 and can run in parallel.

### Workflow drift control (roadmap:515-526) — take the parity branch, not the generator

Generating workflow packages from shared fragments is over-engineering at 15. The workflows
share step *shapes*, but their value is hand-written prompt prose (e.g.
`lifecycle-story-delivery/workflow.yml:52-66`) that must be readable in review; a generator
hides it behind a template layer and doubles review surface. Roadmap:518 offers the
alternative itself — "or tested for semantic parity". Take it.

`tests/test_workflow_parity.py`, driven by declarations in `tooling/invariants.yml`
(`standalone`, `embedded_in`, `branch_step_prefix`), normalises both sides — strip the prefix,
drop `integration:`/`id`, collapse prose whitespace — and asserts the `(kind, command_or_type,
normalised_args)` sequences are equal, failing with a unified diff. ~80 lines, both files stay
hand-editable. Revisit the generator only at a 5th consumer or a 3rd standalone/embedded pair.

Do generate `bundle.yml` and `catalogs/*.json` — pure derived data, 4 files × 15 workflows.

---

## P9–P14 — Hardening, acceptance, pilots, publish

Unchanged in substance from roadmap Phases 7–11 **except P14**, which loses catalog mechanics
to P0c and retains only publication: replacing the placeholder catalog root with real URLs,
cutting immutable releases, publishing checksums and provenance, running the hosted-catalog
install, and issuing the compatibility matrix and support policy. Because P0c already proved
the lifecycle over a `file://` catalog, P14 changes one generator parameter rather than
exercising the mechanism for the first time.

P11 (OpenCode bootstrap) is deliberately last of the feature phases: `policy/model-routing.yml` is entirely
null in both copies, so there is no existing substance to preserve, and the correct role set
is unknown until P13 pilots produce evidence.

**`lifecycle-agent-bootstrap` packaging depends on H8.** The bundle ships `components/` only,
so a bare `scripts/resolve_opencode_models.py` at repo root has no install path. If H8 passes it
stays a workflow and the inventory of 15 stands — but it then adds a third entry to the shell
allowlist (today exactly `devbox run verify` and `devbox run release-verify`,
`validate_source.py:24-27`), which needs security review. If H8 fails, the inventory is 14
workflows plus one out-of-band script, and the roadmap's count must change.

---

## CI at 1.0

| Job | Trigger | Runs |
|---|---|---|
| `lint` | PR, push | `ruff check`, `ruff format --check`, `mypy scripts tests` |
| `source` | PR, push | `validate_source.py --format json`, `generate_* --check`, `validate_requirements.py` |
| `unit` | PR — 3 OS × py3.11–3.13 | `pytest -m "not requires_specify and not sandbox"` |
| `official` | PR (ubuntu), push | install `specify`; `bundle validate --path bundle/ --offline` (D6: the online form cannot pass from a checkout); `bundle build --path bundle/`; `test_packaging.py` |
| `sandbox` | PR (ubuntu slice), nightly (full), tag | `pytest -m sandbox` over the matrix |
| `coverage` | PR, non-blocking | `validate_requirements.py --report md` → step summary |
| `compat` | nightly, `continue-on-error` | installs `specify@main` — upstream breakage surfaces without blocking PRs |
| `release` | tag `v*` | all above + `--strict-publish`, per-component + bundle build, `SHA256SUMS`, build-provenance attestation, **hosted-catalog install and online `bundle validate`**, asset upload |

Matrix (roadmap:249-256): `os` × `repo_state` (empty / existing-speckit / non-git) ×
`install_source`, plus a monorepo-member include. **PR runs the ubuntu slice only**; full
matrix nightly and on tag.

The roadmap's `install_source` axis needs correcting for D7. "Built ZIP" is not an install
source — `bundle install <zip>` reads only the manifest and resolves components outward, so it
fails in a clean repo. The real axis is:

| Value | Meaning | Available from |
|---|---|---|
| `dev-dir` | per-component `--dev` adds | today; bypasses bundle bookkeeping (D5) |
| `local-catalog` | `file://` catalog over built per-component zips | P0c — the CI default |
| `hosted-catalog` | published catalog by bundle id | P14; release job only |

The `lifecycle` dimension is *not* a matrix axis — install → list → info → second install →
update → remove → reinstall is the body of one sandbox test asserting idempotence at each step.

Installing the CLI: `astral-sh/setup-uv@v5`, then
`uv tool install --from git+https://github.com/github/spec-kit.git@v1.0.1 specify-cli`, then
append `$(uv tool dir)/bin` to `$GITHUB_PATH`. Pin the tag.

A placeholder catalog root is a warning on PR and an error at release. Because P0c makes the
catalog root a generator parameter, `YOUR-ORG` stops being a defect to scan for and becomes a
value that is simply unset until P14.

---

## Roadmap amendments (line-referenced, applied in P0e)

| Line(s) | Action |
|---|---|
| 3 | **delete** "pilot-ready" → "unvalidated 0.1.0 baseline; no official validate, build, install, or smoke run has ever succeeded (`VALIDATION.md:31-47`)" |
| 19 | "frozen baseline" → frozen in *scope*, not correctness; P0a/P0b may change every manifest |
| 62-69 | add the missing target line "1 tooling/CI/packaging/docs layer"; footnote `lifecycle-agent-bootstrap`'s packaging form |
| 73-79 | insert a `0.1.0-spike` row before `0.1.1`, exit condition = H1–H9 recorded |
| 83 | "Do this before adding more features" → "…after the substrate is proven" |
| 189-208 | state explicitly whether Devbox replaces Make+pip; delete the duplicate 5-target list if the Makefile stays |
| 210-216 | **move** out of Phase 1 into P0a — this is the invalidating check and must not sit four sections deep. Also correct the command: the source-repo form is `specify bundle validate --path bundle/ --offline`; the online form cannot pass from a checkout (D6) |
| 218-234 | **rewrite.** The install/list/info/update/remove sequence cannot run against a built ZIP (D7). Restate it as a catalog-mediated lifecycle and note it is unreachable until P0c stands up a `file://` catalog |
| 236-245 | "Verify composition" must add H7 (does 10/`append` layer over 20/`replace`, given lower-wins?) and H2 (are these keys legal in `bundle.yml` at all?) |
| 249-255 | add a **Spec Kit version** row to the compatibility matrix; replace the "built ZIP" install-source value with `dev-dir` / `local-catalog` / `hosted-catalog` (D7) |
| 443-449 | note 1.0.1 requires `cases` on `switch` steps |
| 596-602 | state `lifecycle-agent-bootstrap`'s packaging form; note root `scripts/` is not shipped |
| 657, 743-749, 1104 | **delete** the GitHub App; replace with `gh`/fine-grained PAT (local) + `GITHUB_TOKEN` (CI) and an explicit out-of-scope statement |
| 1049-1066 | note `capture`/`link` are wired into **zero** workflows; name P5 as the phase that wires or deletes them |
| 1068-1069 | assess `speckit.taskstoissues` overlap. Also: the governance preset addends **9** core commands; upstream ships **10** — a gap the validator's hardcoded 9-name list actively conceals |
| 1075-1094 | **replace** the dependency graph: GitHub adapter core must precede backlog workflows, not parallel them |
| 1120-1141 | **keep** the slice — it was correct; the sequence around it was wrong |
| 1143-1154 | **replace** the ordered list: it puts remaining GitHub operations after `agent-bootstrap`, while the first slice needs the adapter first |
| 998-1012 | **split Phase 11.** Catalog *mechanics* move to P0c; only publication (real URLs, releases, checksums, provenance, support policy) stays here. The current text treats hosting as final polish, which D7 disproves |
| 1213-1217 | **superseded.** P0a has run; its evidence is `docs/evidence/substrate-1.0.1.md`. Replace with: "Run P0b conformance fixes, then P0c's catalog harness. Do not author new workflows until the install lifecycle is provable end-to-end." |

---

## Verification

**P0a** — the spike is self-verifying: `docs/evidence/substrate-1.0.1.md` contains verbatim
exit codes and stderr, and the H1–H9 table is either complete or the phase is not done. Every
FAIL becomes a defect with a classification.

**P0d** — the acceptance test for the whole tooling rewrite is a single measurable claim:

```
adding a workflow touches exactly one directory
```

Verify by adding a throwaway `components/workflows/lifecycle-scratch/`, running
`make generate && make validate && pytest`, and confirming `bundle.yml` and all four catalogs
regenerate correctly with no other file edited. Then delete it.

Also: `pytest tests/test_check_negatives.py` must fail if any registered check lacks a negative
fixture — proving the checks can fail, which the current suite never establishes.

**P0b** — `specify bundle validate --path bundle/ --offline` exits 0; `grep -rn '0\.16\.5'`
over `*.yml`/`*.json`/`*.md` returns nothing outside `docs/evidence/`; `specify extension add
--dev` scaffolds `.specify/extensions/github-lifecycle/github-lifecycle-config.yml` (D1); and
`specify bundle build --path bundle/` produces an artifact whose file list contains no
`scripts/`, `tests/`, `tooling/`, `dist/`, `.github/`, or `.claude/` entry (D2 — it contained
all six before the relocation).

**P0c** — the decisive end-to-end proof, in a scratch repo with a `file://` catalog and **no**
`--dev` adds:

```
specify bundle install lean-full-lifecycle
specify bundle list      # must report 10 components, not 0
specify bundle info lean-full-lifecycle
specify bundle install lean-full-lifecycle   # idempotent
specify bundle update lean-full-lifecycle
specify bundle remove lean-full-lifecycle    # must actually uninstall
specify preset list                          # must be empty of our two presets
```

Every one of these either errored or silently no-opped during P0a. This sequence going green
is the gate that unblocks P3 onward.

**P1** — `scripts/validate_requirements.py` exits 0; deliberately break bidirectionality (remove
one `@pytest.mark.req`) and confirm it errors.

**P3–P8** — each phase's exit gate is its own sandbox test in `tests/sandbox/` plus the roadmap's
existing per-phase acceptance scenario tables, now expressed as pytest node ids referenced from
`requirements.yml`.

**P12–P14** — the roadmap's 1.0.0 release gate block (`:1016-1031`) is the final check, run by
the `release` CI job on the `v1.0.0` tag.

---

## Sequencing

**Done:** `git init` + baseline (`b700f30`); P0a spike + evidence (`892309e`).

Next, in order:

1. **P0b** — raise the pin to `>=1.0.1,<2.0.0`; fix D1 (one line in `extension.yml`); relocate
   the shipped surface into `bundle/`; write the version ADR. Settle the root `policy/`
   question. The relocation touches every script and doc path, so it lands before anything is
   generated.
2. **P0c** — per-component artifact build, catalog generator with a parameterised root,
   `file://` catalog wiring, and the reusable test fixture. Ends when the install lifecycle
   above is green. **This is the phase that unblocks every later exit gate**, and it is
   entirely new work the original roadmap deferred to Phase 11.
3. **P0d** — `pyproject.toml` + pytest/jsonschema; `scripts/lib/inventory.py` +
   `tooling/bundle-meta.yml`; `generate_manifests.py` and `generate_catalogs.py` with the
   anchor-free dumper; check registry + validator rewrite; test rewrite. Decide
   `install_dev.py`'s fate.
4. **P0e** — doc truth pass, roadmap amendments, GitHub App ADR.
5. **P1** traceability, then CI.

P0b through P0d are the prerequisite for the eight new workflows. Doing the workflows first
means eight PRs each hand-editing five files, none of which could be installed to test.

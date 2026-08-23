# Substrate reality check — Spec Kit 1.0.1

Evidence run for roadmap phase P0a. Recorded 2026-08-23 against the frozen
`0.1.0` source at commit `b700f30`.

Environment: macOS (Darwin 25.5.0, arm64), Python 3.13.12, `specify` 1.0.1
installed via `uv tool install --from git+https://github.com/github/spec-kit.git@v1.0.1`
(resolved commit `9118ed1`). Before this run, no Spec Kit CLI had ever been
executed against this source.

## Verdicts

| ID | Hypothesis | Verdict |
|---|---|---|
| H1 | `bundle validate --path .` passes on 1.0.1 unmodified | **PASS (offline) / FAIL (online)** — see D6 |
| H2 | `priority`/`strategy` are legal on `bundle.yml:provides.presets[]` | **PASS** |
| H3 | `extension.yml:requires.tools` list-of-mappings survives 1.0.1 | **PASS** |
| H4 | A bundle may `provide` a preset it does not ship (`lean`) | **PASS** |
| H5 | `bundle install` accepts a local artifact | **PARTIAL** — accepts the path, ignores its contents. See D7 |
| H6 | YAML anchors survive strict parsing | **PASS** |
| H7 | priority 10 + `append` composes on top of priority 20 + `replace` | **PASS** |
| H8 | A workflow package can ship and execute an auxiliary script | **NOT TESTED** — deferred to P11 |
| H9 | `speckit.taskstoissues` resolves without conflicting with `capture`/`link` | **PASS** — core-only command, no preset layer, no conflict |

The manifest schema is sound. Every failure below is an architecture or
tooling defect, not a schema-drift defect. The `>=0.16.5` pin crossed a major
boundary without breaking the manifests.

## H7 — composition is correct

`specify preset resolve` in a project with `lean` at priority 20 and
`lean-full-lifecycle-governance` at priority 10:

```
Composition chain:
  1. [base]   lean v1.0.0
  2. [append] lean-full-lifecycle-governance v0.1.0
```

"Lower priority number = higher precedence" is confirmed by the CLI's own
output. The repo's configuration is right, and the concern that `append` at a
higher precedence would have nothing to append to is unfounded.

Of the 9 core commands the governance preset addends, `lean` supplies a base
for only 5 (`constitution`, `specify`, `plan`, `tasks`, `implement`). For
`clarify`, `checklist`, `analyze`, and `converge` the **core Spec Kit template**
is the base and `lean` contributes nothing. Composition still resolves
correctly: `speckit.converge` materializes to 292 lines — core body at 11-277,
governance addendum appended at 278-292. `specify preset resolve` shows only
preset layers, so it understates the chain for those four.

Upstream ships a tenth core command, `speckit.taskstoissues`, which the
governance preset does not addend and the roadmap never mentions.

## Defects

| ID | Defect | Class |
|---|---|---|
| D1 | `extension.yml` config target `name: github-lifecycle` never scaffolds | manifest-schema |
| D2 | `bundle build` sweeps the whole repo into the artifact | script-assumption |
| D3 | `build_release.py`'s 10-zip output is superseded by one official zip | script-assumption |
| D4 | `bundle info <id>` requires a catalog; fails for a locally installed bundle | false-doc-claim |
| D5 | Manual `--dev` adds then `bundle install` records 0 components | script-assumption |
| D6 | Online `bundle validate` can never pass from the source repo | false-doc-claim |
| D7 | A bundle artifact is not self-contained; catalog hosting gates all install testing | cli-surface-drift |
| D8 | **Upstream:** `bundle install` cannot install any workflow from a catalog | upstream-defect |
| D9 | **Upstream:** `bundle install` does not scaffold extension config | upstream-defect |

### D1 — extension config never scaffolds

`specify extension add` warns:

```
Warning: Config templates not scaffolded: github-lifecycle.
```

`ExtensionManager._target_follows_preserved_convention` requires a config
target to be a top-level file ending in `-config.yml` or `-config.local.yml`;
anything else is not preserved across an update and is rejected. The manifest
declares `name: github-lifecycle`, which fails the rule, so
`.specify/extensions/github-lifecycle/` is never populated.

Consequence: every command that reads extension config, and `scripts/doctor.py`'s
config lookup, operate against a file that has never existed on any install.
`scripts/validate_source.py` asserts the safety keys inside
`config-template.yml` but never checks that the template is reachable, so this
passed local validation for the whole life of the repo.

Fix: `name: github-lifecycle-config.yml`.

### D2 — build packages the entire repository

`specify bundle build --path . --output <dir>` produced
`lean-full-lifecycle-0.1.0.zip` with **123 files**, including:

```
dist/            16 files, incl. all 10 stale 0.1.0 component zips
scripts/          5 files (validate_source.py, install_dev.py, ...)
tests/            1 file
.github/          1 file
.specify/        12 files (catalog cache, created by the validate run itself)
.claude/          1 file
.gitignore
```

`packager.EXCLUDE_NAMES` is exactly `{".git", "__pycache__", ".DS_Store"}`.
There is **no `.bundleignore` support** — grep of `packager.py` returns nothing.
The published artifact would therefore embed a nested copy of every prior
release artifact.

This invalidates the plan's assumption that a `.bundleignore` could keep
`tooling/` out of the artifact. The only mechanisms available are: keep
development files out of the bundle directory entirely (move the bundle root to
a subdirectory), or accept that they ship.

`.specify/` appearing at all is a second-order effect: running
`bundle validate` in the repo root creates a catalog cache there. It is now
in `.gitignore`.

### D6 — online validate cannot pass from the source repo

```
specify bundle validate --path .
→ Unresolved reference extension:github-lifecycle@0.1.0: ... is not bundled,
  installed, or present in any active catalog.        (and 8 more)

specify bundle validate --path . --offline
→ ✓ lean-full-lifecycle is well-formed and valid.     (7 warnings)
```

`bundle_validate` computes `ref_root = find_project_root(manifest_path.parent)`,
then `references._resolved_locally` accepts a component only if it is shipped
inside the Spec Kit CLI or already installed in *that* project. The repo's
`components/` directory is never consulted. Resolution is therefore a property
of the environment, not of the source tree.

`--offline` downgrades unverifiable references to warnings and passes. **That is
the source-authoring validation mode**, and it is what CI must run. The online
form is for verifying a published bundle resolves from catalogs, and it can only
pass from a project that already has the components installed.

`VALIDATION.md` and the roadmap both present `specify bundle validate --path .`
as the authoritative source check. It is not.

### D7 — the artifact is not self-contained

In a clean project with no prior installs:

```
specify bundle install lean-full-lifecycle-0.1.0.zip
→ Error: Extension 'github-lifecycle' not found in any catalog.
```

`primitives.py` gives each component exactly two install sources: an asset
shipped inside the Spec Kit CLI (`_locate_bundled_extension`), or a catalog
download. **The contents of the bundle zip are never used to install its
components.** `bundle build` produces a source archive; `bundle install` reads
only the manifest and resolves references outward.

Consequences, in order of impact:

1. The bundle cannot be installed by any user until its components are
   published to a reachable catalog. Replacing `YOUR-ORG` and hosting catalogs
   is a **prerequisite for end-to-end install testing**, not release polish.
   The plan schedules this at P14; it must move to roughly P0b/P2.
2. `scripts/install_dev.py`'s per-component `--dev` adds are not a convenience
   path — they are the only way to install this bundle locally today.
3. Catalog URLs accept `file://` and bare local paths
   (`catalog_config._is_local_path`), so a local catalog can close the gap for
   CI and development without publishing anything. This is the recommended
   route and should be proven in P0b.

### D5 / D4 — bundle bookkeeping and lifecycle

Installing components manually and then running `bundle install` attributes
nothing to the bundle:

```
specify bundle install <zip>   → ✓ Installed (0 added, 10 already present)
specify bundle list            → lean-full-lifecycle v0.1.0 (0 components)
specify bundle remove          → ✓ Removed (0 uninstalled, 0 kept)
specify preset list            → both presets still installed
specify workflow list          → all 7 workflows still installed
```

`remove` is a silent no-op after a `--dev` install. `bundle update` and
`bundle info` both fail outright with "not found in any configured catalog".

Roadmap Phase 1's exit gate requires update, remove, and reinstall to pass.
None of the three can pass without a catalog, which is the same blocker as D7.

Second `bundle install` is genuinely idempotent, and installing all seven
workflows and both presets succeeded without error.

## What this changes in the plan

1. **Catalog hosting moves early.** D7 makes it a dependency of every
   install/update/remove test, so a `file://` catalog belongs in P0b and the
   real one no later than P2. It is currently P14.
2. **CI validates with `--offline`.** Per D6, the online form cannot pass from a
   source checkout. The `official` CI job must use `--offline` for the source
   gate and reserve online validation for a post-publish check.
3. **`.bundleignore` is not available.** Per D2, the P1 decision to place
   `tooling/` at the repo root cannot be protected by an ignore file. Either the
   bundle root moves to a subdirectory, or `tests/test_packaging.py` becomes an
   assertion that we knowingly ship development files. Recommend the former.
4. **`build_release.py` is superseded** (D3) and should be deleted in P0c rather
   than refactored.
5. **D1 is a one-line fix** and should land immediately in P0b, with a
   validator check that config templates resolve.
6. **The version pin is safe to raise.** No manifest required any change to pass
   1.0.1 validation, so `>=1.0.1,<2.0.0` carries no migration cost.


---

# P0c addendum — catalog harness findings

Recorded 2026-08-23 while building the local catalog harness. These refine D7
and add two upstream defects that only surface once a catalog exists.

## Catalog mechanics

There are **four independent catalog registries**, not one:
`.specify/preset-catalogs.yml`, `.specify/extension-catalogs.yml`,
`.specify/workflow-catalogs.yml`, and `.specify/bundle-catalogs.yml`. A bundle
install needs all four registered.

They do not share a signature:

| Group | Required | Optional | Notes |
|---|---|---|---|
| `preset` | `--name` | `--priority`, `--install-allowed` | defaults to discovery-only |
| `extension` | `--name` | `--priority`, `--install-allowed` | defaults to discovery-only |
| `workflow` | none | `--name` | accepts neither `--priority` nor `--install-allowed` |
| `bundle` | none | `--policy`, `--priority`, `--id` | also accepts `file://` and bare paths |

**Component catalogs must be HTTPS.** Only `bundle catalog add` accepts
`file://`. All four accept plain HTTP for `localhost`, `127.0.0.1`, and `::1`,
so the harness serves `dist/` over `http://localhost:<port>` rather than
`file://` as originally planned.

**Entry schema differs by kind.** Presets, extensions, and bundles key the
archive as `download_url`; **workflows use `url`**. A workflow entry with
`download_url` is accepted, listed, and searchable, and fails only at install
with "does not have an install URL in the catalog".

**Catalogs are cached per project** under `.specify/<kind>/.cache/`. A changed
`download_url` is not picked up until the cache is cleared, which silently
serves the previous URL.

## D8 — `bundle install` cannot install a workflow from a catalog

`bundler/services/primitives.py` installs a workflow with:

```python
lambda: workflow_add(component.id)
```

`workflow_add` is a Typer command whose second parameter is
`dev: bool = typer.Option(False, "--dev", ...)`. Called as a plain Python
function, `dev` keeps its `typer.OptionInfo` default, which is **truthy**, so
every catalog install takes the local-path branch and fails with:

```
Error: --dev source must be a workflow YAML file, supported archive, or
directory containing workflow.yml: lifecycle-greenfield-bootstrap
```

Confirmed present in 1.0.1 and on `main` at time of writing.
`workflow_remove` is unaffected: it declares only a `typer.Argument`, which the
bundler supplies positionally.

**Workaround:** install workflows through the CLI
(`specify workflow add <id>`) before `bundle install`, which lets Typer bind
`dev=False`. They are still catalog-sourced; only the call path differs.

**Cost:** `bundle install` then reports them "already present" and does not
attribute them, so the bundle records 3 components rather than 10 and
`bundle remove` leaves the workflows installed. Functionally every component is
present and correct; only bundle-level bookkeeping is degraded.

## D9 — `bundle install` does not scaffold extension config

`ExtensionManager.scaffold_config` is called from the `specify extension add`
command flow, never from the bundler primitive. A bundle-installed project
therefore has `config-template.yml` but no `github-lifecycle-config.yml`, even
after the D1 fix.

`doctor.py` now reports `config_source` as `scaffolded`, `template-only`, or
`missing` rather than treating absence as failure, and names the remedy.

## Status of the P0c exit gate

`scripts/smoke_test.py` runs the full lifecycle over the local catalog: 14
checks, all passing. Install, info, composition, idempotent reinstall, update,
remove, and reinstall-after-remove all work. The single deviation from the
original gate is the component count, which is 3 rather than 10 for the reason
D8 gives.

## Recommended upstream reports

Both D8 and D9 are Spec Kit defects, not bundle defects, and are worth filing.
Neither has been reported: filing is left to the maintainer.

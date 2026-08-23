# Validation status

Current as of 2026-08-23, Spec Kit `1.0.1`, macOS (Darwin 25.5.0, arm64),
Python 3.13.

## Verified

```text
python scripts/validate_source.py
→ 15 checks, 0 errors

python -m pytest
→ 49 tests PASS

specify bundle validate --path bundle/ --offline
→ well-formed and valid

specify bundle build --path bundle/ --output dist/
→ lean-full-lifecycle-0.1.0.zip, 58 files

python scripts/smoke_test.py
→ 14 checks PASS

devbox run validate / test
→ toolchain provisioned, delegated to make, PASS

devbox services up catalog
→ process-compose service Ready, catalog served over http://localhost:8899
```

The smoke test is the meaningful one: it installs the bundle into a scratch
project from a local catalog and exercises install, list, info, composition,
idempotent reinstall, update, remove, and reinstall-after-remove. Every step in
that sequence either errored or silently no-opped before the catalog harness
existed.

Invariants enforced by `validate_source.py`, each with a negative fixture
proving it can fail (`tests/test_check_negatives.py`):

- owned preset composes over the external preset at a lower priority number;
- exactly one extension;
- component versions match the bundle version;
- one declared Spec Kit range, present in every manifest;
- canonical policy mirrored byte-identically into the installable preset;
- workflow shell steps restricted to an allowlist, with no interpolation;
- every gate declares a verdict input admitting an empty default;
- every workflow step references a command some component provides;
- every state-mutating step sits behind an approval gate;
- transitions name a plan a prior step actually wrote;
- extension config safety defaults, and a config target Spec Kit preserves.

## Not verified

| Area | Why |
|---|---|
| `devbox run verify` / `release-verify` | Commands the *target project* provides; the bundle only calls them. Devbox itself is verified here, but no product repository has been wired up to exercise these. |
| OpenCode as a running agent | The integration installs and commands materialize, but no workflow has been executed end to end by an agent. |
| Linux and Windows | Only macOS has been exercised. |
| Hosted catalog install | Only the local `http://localhost` catalog. The published path is P14. |
| Workflow execution | No workflow has been run past its first gate. |
| Overlay behaviour beyond update | Overlays are verified across bundle update, workflow update, and reinstall. Conflicting overlays and overlay ordering are untested. |

## Known defects

Three affect installation and are recorded in
`docs/evidence/substrate-1.0.1.md`:

| Defect | Effect | Status |
|---|---|---|
| D5 | `--dev` installs are never attributed to the bundle, so `bundle remove` skips them | inherent to that path; use the catalog path |
| D8 | `specify bundle install` cannot install any workflow from a catalog | upstream, github/spec-kit#4282; worked around |
| D9 | `specify bundle install` does not scaffold extension config | upstream, github/spec-kit#4283; worked around |

Because of D8, the bundle records 3 of its 10 components. Every component
installs and works; only bundle-level bookkeeping is degraded.

## Publishing

`publishing.org` in `tooling/bundle-meta.yml` is unset, so the generated
catalogs emit `UNSET` download URLs rather than a plausible-looking placeholder.
The bundle is not installable by anyone else until it is published (P14), which
requires the repository to be public.

`python scripts/validate_source.py --strict-publish` currently fails, by design:
it reports the unset catalog root and the remaining `YOUR-ORG` strings in prose
documentation.

## Artifacts

`specify bundle build --path bundle/` produces the canonical bundle archive. It
is a manifest of references and is **not** installable on its own.

`python scripts/build_release.py` produces one archive per component. These are
what a catalog serves and what `specify bundle install` actually downloads.

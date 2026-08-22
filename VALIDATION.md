# Validation status

## Completed in this build environment

```text
scripts/validate_source.py
→ PASS

python -m unittest discover -s tests -v
→ 8 tests PASS

scripts/build_release.py
→ 10 local component/source artifacts built
```

Validated invariants include:

- bundle/component IDs and versions;
- official Lean + additive governance priority/strategy;
- preset append-only contributions;
- extension command namespace and safety defaults;
- seven workflow manifests;
- declared gate verdict inputs;
- fixed, non-interpolated shell commands only;
- approved lifecycle plan + human gate before every GitHub transition;
- canonical policy embedded identically in the source and installable preset;
- catalog JSON syntax and version consistency;
- dry-run local installer behavior.

## Not completed here

The following tools are not installed in this execution environment:

```text
specify
devbox
opencode
gh
```

Therefore this source release has **not** been claimed to pass:

```bash
specify bundle validate --path .
specify bundle build --path . --output dist/
python scripts/smoke_test.py --integration opencode
```

Run those in an environment with Spec Kit 1.0.1 or later before publishing or
using the catalogs as an install source.

## Publishing placeholders

`YOUR-ORG` remains intentionally unresolved. Local development installation is
supported; catalog publication is not ready until those placeholders are
replaced and `python scripts/validate_source.py --strict-publish` passes.

## Artifact terminology

The top-level downloadable ZIP is a **source release**.

Files under `dist/` are local component archives produced by the helper. The
canonical installable bundle ZIP must be produced by:

```bash
specify bundle build --path . --output dist/
```

# Publishing

## 1. Replace repository metadata

Replace every `YOUR-ORG` occurrence.

```bash
grep -R "YOUR-ORG" .
```

## 2. Validate source

```bash
python scripts/validate_source.py
python -m unittest discover -s tests
```

## 3. Validate with official Spec Kit

```bash
specify bundle validate --path bundle/ --offline
```

Install each component in a clean sandbox project and run:

```bash
specify preset resolve speckit.specify
specify preset resolve speckit.plan
specify workflow info lifecycle-story-delivery
specify workflow run lifecycle-greenfield-bootstrap ...
```

## 4. Build release archives

```bash
python scripts/build_release.py
specify bundle build --path . --output dist/
```

The helper creates component archives and catalog files. The official Spec Kit
command creates the canonical bundle artifact.

## 5. Publish release assets

Upload all archives under `dist/` to release `v0.1.0`.

## 6. Host catalogs

Publish `catalogs/*.json` at immutable/reviewed URLs and register them as
install-allowed in a clean test project.

## 7. Clean-install test

From a fresh project, install by catalog ID and verify:

- all pinned components resolve;
- install is idempotent;
- update/remove work;
- workflows pause/resume;
- preset composition retains Lean;
- GitHub commands remain plan-first.

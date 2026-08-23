# Scripts

Everything here derives from `scripts/lib/inventory.py`, which reads the
component manifests under `bundle/components/`. No script keeps its own list of
components; adding one means creating a directory and running `make generate`.

| Script | Purpose |
|---|---|
| `generate_manifests.py` | Regenerates `bundle/bundle.yml`. `--check` fails on drift. |
| `generate_catalogs.py` | Regenerates the four `catalogs/*.json`, with the catalog root as a parameter. `--check` fails on drift. |
| `validate_source.py` | Runs this bundle's own invariants. `--list-checks`, `--only`, `--scope`, `--root`, `--strict-publish`. |
| `build_release.py` | Builds one archive per component, plus checksums. These are what a catalog serves. |
| `local_catalog.py` | Serves the archives over a local catalog and installs the bundle the way a real user does. |
| `smoke_test.py` | The end-to-end lifecycle gate: install, info, update, remove, reinstall. |

## Two install paths, and why

`local_catalog.py install --target DIR` is the real one. A bundle artifact is a
manifest of references, not a container, so `specify bundle install` resolves
every component from a catalog. Anything claiming to test installation must go
through one.

`local_catalog.py dev-install --target DIR` installs straight from the source
tree with `--dev`. It is faster when iterating on a component's content and
needs no build or server, but components installed this way are never attributed
to the bundle: `specify bundle list` reports nothing and `specify bundle remove`
is a no-op. That is upstream defect D5, recorded in
`docs/evidence/substrate-1.0.1.md`. Do not use it to verify installation.

## Validation

`validate_source.py` covers only what the official CLI cannot know: this
bundle's safety and composition invariants. Structural validation is
authoritative elsewhere:

```
specify bundle validate --path bundle/ --offline
```

The online form resolves references against the project containing the manifest,
so it cannot pass from a source checkout.

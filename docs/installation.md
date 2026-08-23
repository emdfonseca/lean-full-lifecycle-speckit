# Installation

## Where the source lives

Keep this bundle source in a separate repository or tooling directory.

Do **not** unzip the complete source tree into every application repository.

```text
tooling/
  lean-full-lifecycle-speckit/

products/
  product-a/
  product-b/
```

## Local development installation

From the bundle source:

```bash
python scripts/local_catalog.py dev-install --target /absolute/path/to/product-a

python scripts/local_catalog.py install --target /absolute/path/to/product-a
```

`install` is the real path: it builds the component archives, serves them from
a local catalog, registers that catalog with the target project, and installs
the bundle as a published install would. Use it whenever the result needs to
reflect real user behaviour.

`dev-install` installs each component straight from the source tree with
`--dev`. It skips the build and the server, which makes it faster while
iterating on a component's content, but the bundle is never recorded as owning
those components: `specify bundle list` reports nothing and `specify bundle
remove` is a no-op.

Neither copies this repository into the product.

## Published installation

After component archives and catalogs are hosted, run the catalog commands in
the target project, then:

```bash
specify bundle install lean-full-lifecycle --integration opencode
```

The source repository remains separate.

## Existing Spec Kit project

The bundle is integration-agnostic and inherits the project's active
integration. It will not override an incompatible active integration.

## Project-specific customization

Use project-local workflow overlays and `.specify/templates/overrides/`.
Do not edit installed component files directly.

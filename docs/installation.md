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
python scripts/install_dev.py   --target /absolute/path/to/product-a   --integration opencode   --dry-run

python scripts/install_dev.py   --target /absolute/path/to/product-a   --integration opencode
```

The installer:

1. initializes the target as a Spec Kit project if needed;
2. installs the official Lean preset;
3. installs the local governance preset in development mode;
4. installs the local GitHub extension in development mode;
5. installs all local workflow packages;
6. validates and installs the local bundle manifest to record provenance.

It does not copy this repository into the product.

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

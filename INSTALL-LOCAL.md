# Install locally into a product repository

Keep this source in a separate tooling folder. Do not copy the source tree into
the product repository.

```text
tooling/
  lean-full-lifecycle-speckit/

products/
  my-product/
```

## 1. Get the source

```bash
git clone https://github.com/emdfonseca/lean-full-lifecycle-speckit.git
cd lean-full-lifecycle-speckit
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
```

## 2. Install Spec Kit

```bash
uv tool install --from git+https://github.com/github/spec-kit.git@v1.0.1 specify-cli
```

The bundle requires `>=1.0.1,<2.0.0`.

## 3. Validate

```bash
make validate
specify bundle validate --path bundle/ --offline
```

The online form of `bundle validate` resolves component references against the
project containing the manifest, so it cannot pass from a source checkout. Use
`--offline` here.

## 4. Initialize the product repository

```bash
cd /absolute/path/to/my-product
specify init --here --integration opencode --script py
```

## 5. Install the bundle

```bash
cd /absolute/path/to/lean-full-lifecycle-speckit
python scripts/local_catalog.py install --target /absolute/path/to/my-product
```

This builds the component archives, serves them from a local catalog, registers
that catalog with the product repository, and installs the bundle the way a
published install works. A bundle artifact is a manifest of references, not a
container, so a catalog is the only real install path.

For faster iteration while editing a component, `dev-install` skips the build
and server:

```bash
python scripts/local_catalog.py dev-install --target /absolute/path/to/my-product
```

Components installed that way are never attributed to the bundle: `specify
bundle list` reports nothing and `specify bundle remove` is a no-op. Use it to
iterate, never to verify installation.

## 6. Confirm

```bash
cd /absolute/path/to/my-product
specify preset list                       # governance at 10, lean at 20
specify preset resolve speckit.specify    # [base] lean -> [append] governance
specify workflow list                     # seven lifecycle workflows
```

## Known limitations

- `specify bundle install` cannot install workflows from a catalog
  (github/spec-kit#4282), so the installer adds them through `specify workflow
  add` first. They are still catalog-sourced, but the bundle does not own them
  and `bundle remove` will leave them behind.
- `specify bundle install` does not scaffold extension configuration
  (github/spec-kit#4283). Run `specify extension add github-lifecycle` or copy
  `config-template.yml` to `github-lifecycle-config.yml` yourself.
- The workflows call `devbox run verify` and `devbox run release-verify`. The
  product repository must provide those.

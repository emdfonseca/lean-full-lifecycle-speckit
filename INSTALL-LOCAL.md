# Install locally into a product repository

Keep this source in a separate tooling folder.

```text
tooling/
  lean-full-lifecycle-speckit-0.1.0/

products/
  my-product/
```

Do not copy the complete source tree into `my-product`.

## 1. Extract the source release

```bash
unzip lean-full-lifecycle-speckit-0.1.0-source.zip
cd lean-full-lifecycle-speckit-0.1.0
```

## 2. Validate locally

```bash
python scripts/validate_source.py
```

## 3. Preview installation

```bash
python scripts/install_dev.py \
  --target /absolute/path/to/my-product \
  --integration opencode \
  --dry-run
```

## 4. Install

```bash
python scripts/install_dev.py \
  --target /absolute/path/to/my-product \
  --integration opencode
```

The installer initializes Spec Kit if necessary and installs:

```text
official Lean preset
Lean Full-Lifecycle governance preset
GitHub lifecycle extension
seven lifecycle workflows
bundle provenance record
```

The source repository remains separate. The target receives only normal Spec
Kit-installed assets under `.specify/` and the active agent integration's
managed command/skill files.

## 5. Inspect installation

Inside the target:

```bash
specify bundle list
specify preset list
specify extension list
specify workflow list
specify preset resolve speckit.specify
specify workflow info lifecycle-story-delivery
specify integration status --json
```

## 6. Run framework bootstrap

```bash
specify workflow run lifecycle-greenfield-bootstrap \
  -i integration=opencode \
  -i mode=framework-only
```

Then resume human gates with the requested verdict input:

```bash
specify workflow status
specify workflow resume <run-id> --input bootstrap_verdict=approve
```

For a product bootstrap, supply product context through workflow inputs rather
than editing this bundle source.

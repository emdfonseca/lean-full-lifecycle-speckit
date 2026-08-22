# 0001 — Target Spec Kit 1.0.x and package from a dedicated bundle root

Status: accepted
Date: 2026-08-23

## Context

The source declared `speckit_version: ">=0.16.5"` in 18 manifests, catalogs, and
documents. Spec Kit released `1.0.1` on 2026-08-21, tightening manifest
validation, rejecting non-string manifest list members, and requiring a `cases`
block on workflow `switch` steps. No Spec Kit CLI had ever been run against this
source, so the declared range asserted compatibility across a major version
boundary that had never been tested.

The P0a spike (`docs/evidence/substrate-1.0.1.md`) resolved this empirically.

## Decision

**Target `>=1.0.1,<2.0.0`.** Drop 0.16.x support.

**Package from `bundle/` rather than the repository root.**

## Rationale

### Version

Every manifest passed `specify bundle validate --offline` on 1.0.1 without
modification, and the preset composition chain resolved exactly as designed
(`[base] lean` → `[append] lean-full-lifecycle-governance`). The migration cost
is zero, so there is nothing to defer.

`>=0.16.5` was unbounded and therefore *less* conservative than a pinned range:
it already claimed compatibility with every future release, including the one
that tightened validation. Narrowing is the safer change.

No user is known to be pinned to 0.16.x. Dual-support would add a compatibility
matrix dimension and a second CI axis to protect a line with no consumers.

### Bundle root

`specify bundle build` packages the entire bundle directory. Its exclusion list
is exactly `{.git, __pycache__, .DS_Store}` and it honours no ignore file —
there is no `.bundleignore`, contrary to what the extension API's
`.extensionignore` suggests by analogy.

Building from the repository root therefore produced a 123-file artifact
containing `dist/` (including all ten prior release archives), `scripts/`,
`tests/`, `.github/`, `.claude/`, and a `.specify/` cache created by the
validate run itself.

The only mechanism the CLI offers is directory scoping, so the shipped surface
moves to `bundle/` and everything else stays outside it. The same build now
produces 58 files: `bundle.yml`, `README.md`, and `components/`.

This also makes the published command honest: `--path bundle/` names what is
actually packaged.

### Policy placement

Canonical policy stays at the repository root, outside `bundle/`, and is
mirrored into the governance preset. Only the preset copy installs — composed
commands read `.specify/presets/lean-full-lifecycle-governance/policy/` — and
the bundle archive is inert for installation, so a bundle-root copy would ship
in every artifact while never being read. Two copies, not three.

## Consequences

- The source gate is `specify bundle validate --path bundle/ --offline`. The
  online form resolves references against the *project* containing the manifest
  and can never pass from a checkout; it is a post-publish check.
- `scripts/`, `tests/`, `catalogs/`, `docs/`, `policy/`, and future `tooling/`
  are structurally unshippable rather than ignored. No exclusion list to
  maintain.
- The `>=1.0.1,<2.0.0` range must be revisited deliberately for Spec Kit 2.x
  rather than drifting open again. A nightly CI job installs `specify@main` and
  is allowed to fail, so upstream breakage surfaces without blocking work.
- The pin currently lives in 18 places. P0d reduces it to one declared value
  with a consistency check.

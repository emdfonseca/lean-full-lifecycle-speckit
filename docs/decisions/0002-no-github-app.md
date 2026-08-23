# 0002 — No GitHub App for 1.0.0

Status: accepted
Date: 2026-08-23

## Context

`docs/implementation-roadmap.md` proposed moving routine GitHub mutations into
"deterministic, tested scripts or a least-privilege GitHub App", and named a
GitHub App as the organization-automation credential.

Two normative documents already said otherwise:

- `docs/security.md`: "The GitHub extension is a prompt-command integration
  using `gh`. It is not a privileged daemon or hosted service."
- `PACKAGING-DECISIONS.md` lists a hosted service among what is deliberately
  absent.

The roadmap's proposal was the newest and least-justified of the three claims,
and it was never reconciled with either.

## Decision

No GitHub App. The extension authenticates with `gh` and a fine-grained
personal access token locally, and with `GITHUB_TOKEN` or a fine-grained token
held as a secret in CI.

## Rationale

A GitHub App is not a credential; it is a product. It carries a registered
identity, a private key, an installation-token lifecycle, an organization
approval path, and its own release, rotation, and support obligations. This
bundle ships zip archives resolved from a catalog. Adding an App would change
what the project *is*, and it would do so to solve a problem that has another
solution.

Least privilege is achievable without one, and `security.md` already prescribes
how: separate the credential that administers organization schema from the one
that performs routine issue-value transitions. Two scoped tokens deliver the
separation the App was invoked to provide.

Nothing in the acceptance suite needs it. Issue Fields, sub-issues,
dependencies, pagination, rate-limit handling, and read-after-write are all
reachable through `gh` and the REST and GraphQL APIs.

## Consequences

- Phase 6's authentication ladder is two token scopes, not two mechanisms.
- Organization-level automation is bounded by what a fine-grained token can do.
  If a future requirement genuinely exceeds that, it is a new decision with its
  own ADR, not a resumption of this one.
- `docs/security.md` and `PACKAGING-DECISIONS.md` needed no change: the roadmap
  was the document out of step.

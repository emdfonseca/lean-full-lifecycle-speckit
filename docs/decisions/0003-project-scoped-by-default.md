# 0003 — Project-scoped lifecycle fields by default

Status: accepted
Date: 2026-08-23

Supersedes the `scope: organization_preferred` assumption in
`policy/github-schema.yml`.

## Context

`github-schema.yml` declared `scope: organization_preferred` and described
Projects v2 under `fallback.when_issue_fields_unavailable`. That framing has
been in place since before any of it was executed, and it encodes a claim that
turns out to be backwards.

What was established while building the adapter:

- Custom Issue Fields and Issue Types are organization-only. There is no
  repository-scoped equivalent: the `User` type exposes neither,
  `orgs/{org}/issue-fields` is the only route, and `viewerCanSetFields` is false
  on a repository the caller owns.
- Organization Issue Fields apply **organization-wide**. Adding a field to meet
  one repository's needs puts it on every issue in every repository in that
  organization.
- Projects v2 works for both users and organizations, is scopable to a single
  repository, and carries every field the schema requires. It has been verified
  end to end: read, write, read-back, idempotent replay, dry-run.

So the "preferred" path is unverified, unavailable to most adopters, and
imposes org-wide cost; the "fallback" is the one that works and the one a
single-repository adopter will use.

## Decision

Project-scoped fields are the **default**. Organization Issue Fields are an
**opt-in** for organizations that want one lifecycle vocabulary shared across
many repositories.

Neither is a degraded form of the other. They are two deployment shapes with
different blast radii, and the adapter already treats them as peers behind one
interface.

`scope: organization_preferred` becomes `scope: project_scoped_default`, and
`fallback.when_issue_fields_unavailable` becomes a named backend rather than a
contingency.

## Rationale

A default should be the thing that works for the common case without asking
permission. Requiring organization membership, and organization-wide schema
administration, to run a lifecycle in one repository fails both tests.

Calling the working path a fallback also shaped the build order: it made the
verified backend look like a compromise and the unverified one look like the
goal. That is how `REQ-GITHUB-ORGFIELDS-001` came to be written as `must`.

## Consequences

- `REQ-GITHUB-ORGFIELDS-001` drops from `must` to `should` and remains
  `implemented` until an organization actually needs it.
- `authoritative_project_count: 1` moves out of the fallback block: it is a
  property of the default, and ambiguity about which board governs is refused
  rather than resolved.
- `allow_status_labels: false` still holds for both backends. Labels were never
  a backend.
- P13's sandbox organization is still worth having, but it verifies an option
  rather than unblocking the product.
- Documentation that describes organization setup as the intended path needs
  correcting. `docs/tracking.md` already describes this repository running the
  project-scoped model; it is now the documented default rather than an
  accommodation.

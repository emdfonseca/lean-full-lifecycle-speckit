# 0004 — Blocking is a dependency, not a delivery state

Status: accepted
Date: 2026-08-23

## Context

`policy/state-machine.yml` defines Inbox, Refining, Ready, In Progress, and
Output Done. None describes an item that is understood, agreed, and waiting on
something outside this project.

Such items exist. #28, #29 and #123 are specified, worked around, and waiting on
the maintainers of `github/spec-kit`. They sat in Inbox, which reads as
untriaged and misrepresents them.

The obvious fix — add a `Blocked` value — is wrong.

## Decision

The five delivery states stand. Blocking is recorded as a **native issue
dependency**, which is orthogonal to the delivery state and never changes it.

An item that is Ready while blocked is reported by the audit, because it claims
to be startable and is not.

## Rationale

**Blocked is a modal attribute, not a phase.** An item can be blocked while
Refining, while Ready, or while In Progress. Making it a state destroys the
phase: when the block clears, there is no answer to where the item returns to
without storing the previous state — which means storing two things and having
gained nothing over storing one thing and a flag.

**The transition table has no sensible entry for it.** Every edge in
`state-machine.yml` carries an `authority` and `evidence`. For an edge that
exists because somebody else has not finished, neither has an answer. Adding
Blocked would roughly double the table with edges nobody can evidence.

**The policy already had the mechanism.** `github-schema.yml` lists
`issue_dependencies` under `native_metadata` and never connected it to
anything. Dependencies are the orthogonal signal the state machine was missing.

**It works across repositories**, which is what the motivating case needs.
`POST /repos/{owner}/{repo}/issues/{n}/dependencies/blocked_by` takes a global
`issue_id`, so an item here records a blocker in another project. Verified:
#28 is blocked by `github/spec-kit#4282`, #29 by `#4283`.

## Consequences

- No change to `delivery_status.values`. A test asserts they remain five.
- The Ready queue is now two things: items that are Ready, and items that are
  Ready *and unblocked*. Only the second is startable, and only the second
  should be counted when deciding whether the queue needs refilling.
- Refinement can run ahead of implementation. An item with no open blocker can
  be refined to Ready while other work is in flight, because nothing in flight
  can change its shape. An item *with* an open blocker should not be, since the
  blocker may change what it means.
- `#28` and `#29` remain in Inbox. That is now correct rather than a
  misrepresentation: they are untriaged for scheduling because their timing
  belongs to another project, and the dependency records why.

---
description: Validate an exception against the exception policy.
---

# GitHub Lifecycle Exception

```bash
python .specify/extensions/github-lifecycle/scripts/exception.py \
  --record .specify/lifecycle/exceptions/<id>.md
```

An unenforced exception policy is worse than none: it is a document teams cite
while doing the opposite. `exception-policy.yml` names the required fields and
the four forbidden shapes; this refuses records that do not meet them.

## The four shapes, and why each is refused

**Blanket.** "The legacy code" is not a scope. An exception nobody can bound is
one nobody can review. A scope is refused when it names the whole repository, a
directory tree from too near the root, or a family of rules instead of a rule.

**Ownerless.** Present but empty is absent. A placeholder owner is how an
exception survives with nobody to answer for it.

**Permanent without approval.** Permanence is the one disposition that outlives
everybody involved, so it is the one that must say who chose it.

**Hiding new violations.** An exception over a glob cannot tell an existing
violation from one added tomorrow unless it records what existed when it was
written. Without that baseline it widens on every commit.

## Expiry

An exception past its review date is reported, not deleted — deleting it loses
what was accepted and by whom — and it stops suppressing its rule. That is the
whole mechanism. An exception that outlives its review is how a codebase stops
improving while every gate still reports green.

## Never

- Widen a scope, extend a date, or drop a compensating control to get a record
  accepted. Each is the exception deciding its own terms.
- Treat a refusal as an obstacle. It is a finding about the exception.
- Create an exception for a violation that has not been introduced yet.

---
description: Write and check the core documents a bootstrapped project must have.
scripts:
  py: scripts/documents.py
---

# GitHub Lifecycle Documents

`bootstrap-policy.yml` declares under `product_documents` what a project must
have, what each answers, the sections it carries, and how long it may be.

```bash
{SCRIPT} --format json
```

## The budgets are the point

A brownfield adoption produced four artefacts averaging 234 lines — accurate,
well-reasoned, and too long to read before writing a spec. Length is the one
quality property a script can judge, so it is the one this enforces.

A document over budget is reported with the overage named. It is not truncated
and not warned about: the budget is a maximum somebody chose, and a document
that needs more room usually needs less content.

**Evidence does not go in these.** The discovery record and the bootstrap or
adoption report already hold it. Repeating it here makes the one document a
reader must read the one nobody finishes.

## Recovered intent, for an adopted project

`PRODUCT.md` is archaeology in a brownfield project. Intent comes from the
README, the release notes, and merged pull requests — in that order of
authority, the same ranking the discovery record uses. Where intent cannot be
recovered, the section says so. An invented intent is worse than an absent one,
because the next reader believes it.

## Two sections that must not merge

`architecture.md` carries **As built** and **Intended** separately. The first is
observation and carries evidence; the second is a decision and carries an
owner. The gap between them is where specs come from, which is why they are one
document rather than two that drift apart.

## Report

State which documents are missing, which are over budget and by how much, and
which lack a named section. A clean result says so plainly; there is nothing
else to report.

## Never

- Write a document to satisfy the check. An empty `PRODUCT.md` with the right
  headings passes and tells a reader nothing.
- Move content into an evidence record to get under budget without deciding
  whether it was worth writing.
- Fill a section you could not recover. Say it could not be recovered.
- Summarise the document inside the document.

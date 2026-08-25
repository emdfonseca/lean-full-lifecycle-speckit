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

## Form is the point, not length

A brownfield adoption produced four artefacts averaging 234 lines — accurate,
well-reasoned, and too long to read before writing a spec. The first fix
budgeted lines, and that number was wrong for somebody: a constitution set at
200 lines would have meant deleting principles from a real one.

So length is not budgeted and no overage is reported. Form is checked instead
and scales on its own — a table with one row per fact cannot ramble however
large the project, and a section declared as a list shows how many entries it
has. A section that is missing, empty, or in a form the contract did not ask
for is a failure, not a warning.

A constitution is checked principle by principle: each states something
normative in RFC 2119 terms, and states it first. A principle with no MUST is
an opinion, and an explanatory paragraph in front of a rule means the rule is
not yet written.

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

State which documents are missing, which lack a named section, which sections
are empty or in the wrong form, and which principles state no rule or bury it.
A clean result says so plainly; there is nothing else to report.

## Never

- Write a document to satisfy the check. An empty `PRODUCT.md` with the right
  headings passes and tells a reader nothing.
- Move content into an evidence record to shorten a document without deciding
  whether it was worth writing.
- Fill a section you could not recover. Say it could not be recovered.
- Summarise the document inside the document.

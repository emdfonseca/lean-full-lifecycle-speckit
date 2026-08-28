---
description: Workflows, not people — refuse unauthorized production data, and keep credentials out of framework evidence.
scripts:
  py: scripts/sensitive.py
---

# GitHub Lifecycle Sensitive

Two checks, both against `sensitive-data.yml`.

**Before reading a data source:**

```bash
{SCRIPT} \
  --source production_database --authorization .specify/lifecycle/auth-<id>.yml
```

**Before committing a record the framework wrote:**

```bash
{SCRIPT} \
  --record .specify/lifecycle/brownfield-discovery.md --format json
```

Scan every discovery, disposal, outcome, plan, verdict, and exception record.
Those are where production data lands during a brownfield adoption, and they are
read by people long after the run.

## What a finding says

The record and where in it. Never the value. A YAML record reports the field
path; a Markdown record has no fields, so it reports the line. A report that
quotes the secret has
copied it somewhere new — into an issue, a log, a transcript — which is the harm
the scan exists to prevent. If you need to see the value, open the file; do not
paste it into a report, a comment, or a commit message.

## Redaction is visible, and it is not authorization

The marker stays in place so a reader can tell something was removed. Evidence
that was silently cleaned reads as complete and is not.

Redaction happens after the read. It cannot make an unauthorized read
authorized. If a step lacks authorization for a source, it is refused whether or
not the result would have been redacted — treating redaction as permission is
what makes a denial policy decorative.

## Refuse a secret file before it is read

```bash
{SCRIPT} \
  --path <path> --format json
```

`denied_sources` names six places production data lives and none of them is a
file, so it never covered `.env` or a private key. `denied_paths` does. The
refusal names the pattern that matched and why it exists, because a refusal
that does not say what would clear it is one an author switches off.

The same patterns become deny rules in the generated agent configuration — one
per path, naming no reader. Claude Code applies a `Read` deny to its own file
tools and to the file commands it recognises in Bash, so the boundary is the
path rather than a list of readers.

Enumerating readers was tried and removed (#135): four names denied four
spellings of an operation the shell offers a dozen ways, and the next reader not
on the list still passed. What no permission list expresses — a subprocess that
opens the file itself — is reported as unmappable rather than approximated.

If `rules_from_policy` is `false` the installed preset predates this policy.
Say so. The command emitted no rules, so nothing is denied.

## Redact a record

```bash
{SCRIPT} \
  --record <path> --redact --out <path> --format json
```

Redacts the file's text rather than the parsed record, so a document a person
wrote keeps its shape and the diff stays reviewable. The rescan afterwards reads
the record the same way the first scan did.

Report `findings_before`, `findings_after` and `changed`. **A non-zero
`findings_after` stops the record reaching review.** Redaction is not
authorization: it happens after the read, and a value that should never have
been read is still a finding once the marker replaces it.

## Never


- Report a refusal generically. Cite the rule id and text, so the reader knows
  which rule they met and who can lift it.
- Widen a source name, split a read into smaller reads, or summarize production
  data to get past a denial. Each is the same read.
- Continue when the patterns did not come from policy. `patterns_from_policy:
  false` means the governance preset is not installed, and a conservative
  fallback ran instead. Say so.

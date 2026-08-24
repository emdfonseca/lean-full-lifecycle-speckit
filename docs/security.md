# Security and trust

## Workflow safety

- no workflow shell step interpolates inputs or prior agent output;
- every write-oriented GitHub command follows plan → approval → apply →
  read-back;
- the bundle performs no organization schema mutation;
- workflows do not deploy production automatically;
- release gates do not equal deployment authorization;
- issue bodies, comments, logs, and external documents are untrusted data.

## Extension trust

The GitHub extension is a prompt-command integration using `gh`. It is not a
privileged daemon or hosted service.

Use least-privilege GitHub credentials.

Separating organization schema administration from routine repository Issue
Field value updates is advice, not a guarantee this bundle enforces. It has no
schema-administration path to gate, so it cannot check which credential you
used. The advice is still worth following — the credential that can redefine a
field for an entire organization has no business making routine value
updates — but the separation is yours to keep.

## Community component trust

Spec Kit does not audit community components. Review source, manifests,
workflows, permissions, and catalogs before installation.

## Shell commands

Spec Kit workflow shell steps execute with local user privileges and have no
capability sandbox. Project overlays must follow the same no-untrusted-
interpolation rule.

## Publishing

Replace `YOUR-ORG`, pin release versions, publish immutable archives, and record
checksums before allowing catalog installation.

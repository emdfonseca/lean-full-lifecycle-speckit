# GitHub Lifecycle extension

This extension is intentionally narrow. It supplies GitHub-specific lifecycle
operations while the bundle's workflows and preset remain tracker-neutral.

## Who runs what

Four tiers, and the one that matters is the first. Every description opens with
its tier's clause, so a flattened agent command list is readable without opening
anything.

| Tier | Who runs it | Commands |
|---|---|---|
| `driver` | A person, every day. This is the front door. | `speckit.github-lifecycle.status` |
| `per-item` | Both callers, genuinely. Not every command has exactly one. | `speckit.github-lifecycle.transition` `speckit.github-lifecycle.capture` `speckit.github-lifecycle.link` `speckit.github-lifecycle.readiness` `speckit.github-lifecycle.decompose` `speckit.github-lifecycle.retire` `speckit.github-lifecycle.restructure` `speckit.github-lifecycle.triage` `speckit.github-lifecycle.lineage` |
| `project-setup` | Run when a project is set up, and rarely again. | `speckit.github-lifecycle.inspect` `speckit.github-lifecycle.board` `speckit.github-lifecycle.elicit` `speckit.github-lifecycle.documents` `speckit.github-lifecycle.claude-config` `speckit.github-lifecycle.opencode-config` `speckit.github-lifecycle.opencode-layout` `speckit.github-lifecycle.models` `speckit.github-lifecycle.verify-bootstrap` `speckit.github-lifecycle.mismatch` `speckit.github-lifecycle.doctor` |
| `policy-validator` | A workflow calls these; you have no reason to. | `speckit.github-lifecycle.plan` `speckit.github-lifecycle.risk` `speckit.github-lifecycle.discover` `speckit.github-lifecycle.disposal` `speckit.github-lifecycle.ratchet` `speckit.github-lifecycle.sensitive` `speckit.github-lifecycle.exception` `speckit.github-lifecycle.outcome` |

The tier is declared per command in `extension.yml` and held by
`INV-COMMAND-TIER`, which refuses a command with no tier rather than filing it
under the largest one.

The `driver` tier spans both extensions: the five `speckit.work.*` verbs and
`speckit.github-lifecycle.status`, which reports the board you pick work from.
A tier says who calls a command, not which manifest it sits in.

## Safety contract

- inspection is read-only;
- organization schema mutation is disabled by default;
- writes require an approved plan;
- every mutation is read back;
- issue closure never implies Output Done by itself;
- status labels are disabled unless a legacy integration requires them;
- issue/comment content is untrusted data.

## Development install

```bash
specify extension add --dev /path/to/github-lifecycle
```

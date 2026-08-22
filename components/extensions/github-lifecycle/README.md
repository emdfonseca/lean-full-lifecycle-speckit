# GitHub Lifecycle extension

This extension is intentionally narrow. It supplies GitHub-specific lifecycle
operations while the bundle's workflows and preset remain tracker-neutral.

## Commands

```text
/speckit.github-lifecycle.inspect
/speckit.github-lifecycle.plan
/speckit.github-lifecycle.transition
/speckit.github-lifecycle.capture
/speckit.github-lifecycle.link
/speckit.github-lifecycle.doctor
```

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

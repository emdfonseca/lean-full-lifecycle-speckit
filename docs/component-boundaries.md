# Why workflows and one extension

Use a workflow when the behavior is sequencing, gating, looping, or invoking
existing Spec Kit commands.

Use an extension when the behavior introduces a reusable command or external
integration.

This bundle therefore uses:

```text
1 official Lean preset
1 additive governance preset
14 workflows
1 GitHub extension
0 custom runtime step types
```

The GitHub extension is separated so tracker permissions and provider details
do not leak into core lifecycle policy.

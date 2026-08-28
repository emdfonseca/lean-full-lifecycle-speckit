# Work extension

Five commands that drive one work item through the lifecycle from inside the
session, over one router that decides the next step from policy.

## Who runs what

Four tiers, and the one that matters is the first. Every description opens with
its tier's clause, so a flattened agent command list is readable without opening
anything.

| Tier | Who runs it | Commands |
|---|---|---|
| `driver` | A person, every day. This is the front door. | `speckit.work.status` `speckit.work.start` `speckit.work.continue` `speckit.work.change` `speckit.work.finish` |

The tier is declared per command in `extension.yml` and held by
`INV-COMMAND-TIER`, which refuses a command with no tier rather than filing it
under the largest one.

The `driver` tier spans both extensions: the five `speckit.work.*` verbs and
`speckit.github-lifecycle.status`, which reports the board you pick work from.
A tier says who calls a command, not which manifest it sits in.

## What the router will not do

It reads no board -- board facts are arguments, so every transition still goes
through `speckit.github-lifecycle.transition` and its `--expect` guard -- and it
persists nothing. A step is finished when the artifact its workflow declares it
`produces` is in the feature directory; a step that produces nothing nameable is
reported unverifiable rather than guessed at.

It names no delivery state. The entry state, the terminal states, the retirement
target and the forward transition are derived from `state-machine.yml`, and the
workflow that carries an item at a state comes from `item-types.yml`.

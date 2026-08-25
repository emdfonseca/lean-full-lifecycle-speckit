# Monorepo and worktree run

Stream 3 of four. The metrics record is `docs/evidence/pilot-monorepo.md`; this
is what was run and what held.

| | |
|---|---|
| Target | a two-member Spec Kit monorepo, built for this run, plus a git worktree of it |
| Members | `member_a` and `member_b`, each `specify init` + the full bundle, with different extension configs |
| Outcome | five acceptance criteria exercised, all held, no defect found |
| Operator | agent |

## What this stream verifies

Resolution and containment, not delivery. No workflow ran and no item moved in
the pilot project, which is why most metrics are `not_applicable` rather than
zero. `#105` says as much: it establishes whether what exists holds when the
working directory is not the project root.

## AC4 first, because the issue said to decide it before running

> either scenarios covering this stream exist, and otherwise a recorded
> decision states the stream is narrower than the roadmap's four

There are no monorepo acceptance scenarios. There is no `sandbox-org` group
either, and that stream is **already delivered** as `#37`, with evidence cited
from `requirements.yml` and `compatibility.yml`.

So a pilot stream can be complete without a scenario group, and adding a
`monorepo` group now would impose a shape the one finished stream never needed.
Monorepo is covered as a compatibility-matrix dimension instead, which is the
better instrument here: it can say a behaviour holds under one integration and
is untried under another, and the matrix already records exactly that, with
`monorepo` deliberately absent under `claude`.

Recorded in `docs/plan-corrections.md`.

## What was run

**AC1 — the project root is the member, not the repository.**

| From | Resolved to |
|---|---|
| `member_a` | `member_a` |
| `member_b` | `member_b` |
| `member_a/src/deep/nested` | `member_a` |
| `pilot-mono-wt/member_a` (worktree) | the worktree's own `member_a` |

Neither member resolves to the git root, and the worktree resolves to its own
copy rather than the original.

**AC2 — a write outside the resolved project is refused.** From inside the
worktree, three escape routes:

| `--out` | Result |
|---|---|
| `/tmp/escaped-plan.md` | `OutsideProjectError`, exit 1 |
| `../member_b/stolen.md` | `OutsideProjectError`, exit 1 |
| `../../outside.md` | `OutsideProjectError`, exit 1 |

Each names the absolute path it refused. No file appeared at any of the three,
which was checked rather than inferred from the exit code.

**AC3 — each member reads its own target.**

```
member_a  Target(repo='plaincodelab/member-a-repo', project=11, source='.specify/.../github-lifecycle-config.yml')
member_b  Target(repo='plaincodelab/member-b-repo', project=22, source='.specify/.../github-lifecycle-config.yml')
```

**AC5 — a directory belonging to no member is refused.**

| Command | Exit | First line |
|---|---|---|
| `transition_plan.py queue` | 2 | names `--repo`, the env var, and the config file |
| `documents.py` | 2 | `bootstrap-policy.yml declares no product_documents` |
| `verify_bootstrap.py` | 2 | names the preset paths it looked in |
| `doctor.py` | 0 | reports `specify_project: false`, `config: null` |

`doctor` exiting 0 is correct rather than a finding: it is read-only
diagnostics, and reporting "there is no project here" *is* its successful
answer. It does not guess a root.

## Two errors in how I measured

Neither is a defect in the bundle, and both would have produced a wrong record.

**Exit codes read through a pipe.** My first measurement of AC5 showed `exit=0`
for commands that had visibly refused. That was `tail`'s exit code, not the
script's, because `$?` after a pipeline reports the last stage. Measured
without the pipe, three of the four exit 2. This is the same trap noted on
`#129`, hit from the other side.

**An acceptance criterion that passed without testing anything.** My first AC2
attempt used `--to Refining` on an issue already `In Progress`. The state
machine rejected the transition before the path check ran, so the command
failed for the wrong reason and no file was written — which looks exactly like
containment working. Using a legal transition reached the check, and it fired.

A criterion can pass because the thing under test refused, or because something
upstream refused first. Only the second is worthless, and the two are
indistinguishable from the exit code alone.

## Disposal

The monorepo and its worktree are retained until this record is reviewed. The
worktree is registered with git, so removing it needs `git worktree remove`
rather than deleting the directory, or a stale registration is left behind.

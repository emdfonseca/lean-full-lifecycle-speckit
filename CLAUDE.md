# Working on this repository

A GitHub Spec Kit **bundle**: one governance preset, one GitHub extension, 14
lifecycle workflows. `bundle/` is the shipped surface. Everything else stays
outside it, because `specify bundle build` packages whatever is under the
bundle directory and there is no `.bundleignore`.

## Start here

```bash
E=bundle/components/extensions/github-lifecycle/scripts
.venv/bin/python $E/doctor.py            # is this project wired up
.venv/bin/python $E/transition_plan.py queue   # what is startable
.venv/bin/python $E/transition_plan.py audit   # board against policy
make validate && make test
```

No `--repo` or `--project` needed: they come from
`.specify/extensions/github-lifecycle/github-lifecycle-config.local.yml`.

The board is what is true. Every closed issue carries a comment explaining what
was built and what it exposed — read the issue rather than re-deriving it.

## Where the rules live

They are not repeated here, because a second copy drifts and the copy that
drifts is the one nobody tests.

| Question | Read |
|---|---|
| What may an agent do, and what needs a person | `policy/agent-policy.yml` |
| What a state means and what may follow it | `policy/state-machine.yml` |
| What an item type must contain | `policy/item-types.yml` |
| How a command behaves, and what it refuses | that command's `.md` in the extension |
| Which acceptance scenario is deliverable when | `tooling/acceptance-scenarios.yml` |
| Why the phase order differs from the roadmap | `docs/plan-corrections.md` |
| What is proven under which agent | `docs/compatibility.md` |

## The loop for one story

Refine and validate a readiness verdict, move `Refining` → `Ready` →
`In Progress`, build it, add one requirement with `verified_by` node ids and
`@pytest.mark.req` on each test, run the validators, comment on the issue, move
to `Output Done`, then close, then commit. One story per commit.

`speckit.github-lifecycle.*` commands carry the rest, including what each
refuses and why. Invoke the command rather than reimplementing its judgement.

## Two habits the tooling cannot enforce

**Verify against the real CLI.** `specify`, `opencode`, `claude`, and `gh` are
installed. Reading their actual behaviour has contradicted a reasonable guess
every time it mattered.

**Correct a wrong record before building on it.** #33, #60, and #80 each carry
a correction to their own report. A wrong record is worse than no record.

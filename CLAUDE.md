# Working on this repository

A GitHub Spec Kit **bundle**: one governance preset, one GitHub extension, 14
lifecycle workflows. `bundle/` is the shipped surface; everything else —
`scripts/`, `tests/`, `tooling/`, `docs/`, `policy/` — stays outside it and is
structurally unshippable, because `specify bundle build` packages whatever is
under the bundle directory and there is no `.bundleignore`.

## Start here after a context reset

```bash
R=emdfonseca/lean-full-lifecycle-speckit
E=bundle/components/extensions/github-lifecycle/scripts
.venv/bin/python $E/transition_plan.py --repo $R --project 3 queue   # what is startable
.venv/bin/python $E/transition_plan.py --repo $R --project 3 audit   # board vs policy
```

The board is the source of truth for what is done and what is next. Every
closed issue carries a comment explaining what was built and why, including the
defects found on the way — read the issue before re-deriving its reasoning.

Then: `make validate && make test`. If those are green the tree is consistent.

## The loop for one story

1. Read the issue. Write a readiness verdict and validate it:
   `readiness.py --verdict <file> --issue <n> --repo <r>`.
2. Move `Refining` → `Ready` → `In Progress`. Never skip `Ready`.
3. Build it. Policy first, then the script, then the tests.
4. Add one requirement to `tooling/requirements/requirements.yml` with
   `verified_by` node ids, and `@pytest.mark.req` on each test. The check is
   bidirectional and will refuse either half alone.
5. `make validate && make test && specify bundle validate --path bundle/ --offline`.
6. Comment on the issue: what was delivered, and any defect the work exposed.
7. Move to `Output Done`, **then** close. Closure follows completion.
8. Commit, one story per commit.

An item with an open blocker is not refined to Ready: the blocker may change
what it means (`state-machine.yml: refine_ahead_requires`).

## Rules the code enforces, and why

**Absent evidence must not read as success.** An unreadable repository is not
an empty one; an unreadable `devbox.json` is not a project with no verify
command; an empty model inventory verifies nothing; a dependency list that
could not be read is not "no blockers". Every one of these was a real defect.
When you cannot determine something, say so — do not return the permissive
answer.

**Parse, do not scan.** A substring check cannot tell a rule from its
explanation. It has bitten five times: a docstring explaining why a module does
not read git, a comment naming the paths it deliberately does not hardcode,
`architect` matching "architecture". Use `ast` for code and a declared key for
data.

**A fake must be no more generous than the API.** Tests passed and live calls
failed three times: a fake returning all fields while the real API needs
`?fields=`, one ignoring `?state=`, one with no `/blocked_by` route returning a
bare string. When you add a route to a fake, make it refuse what GitHub
refuses.

**Policy is data; scripts read it.** Values live in `policy/*.yml`, mirrored
byte-identically into the preset. A test asserts the literals are absent from
the script, so changing policy changes behaviour. Two copies of one fact drift,
and the copy that drifts is the one nobody tests.

**A check needs a negative fixture.** `tests/test_check_negatives.py` refuses
any registered check without a case that makes it fail. Write the breaker.

**Assertions must be able to fail.** Do not read an expected value out of the
policy under test. Prose assertions are marked `@pytest.mark.wording` and are
not behavioural coverage.

**Verify against the real CLI.** `specify`, `opencode`, `claude`, and `gh` are
installed. Read their actual behaviour rather than assuming it — this session
found `SPECIFY_INIT_DIR` semantics, the `auto` integration sentinel, and Claude
Code's command layout that way, and each contradicted a reasonable guess.

## Correcting yourself

If you filed an issue that overstated a defect, or a spike reached a wrong
conclusion, correct it on the issue before building the fix. #33, #60, and #80
each carry such a correction. A wrong record is worse than no record.

## Where the phases are

`docs/implementation-roadmap.md` holds the phase sequence (P0a–P14) and the
acceptance suite. `tooling/acceptance-scenarios.yml` assigns each of the 51
scenarios to the phase that can deliver it; nine are blocked on code that does
not exist and name the issue tracking it. `docs/evidence/` holds the
point-in-time audits those assignments came from.

Milestones: 0.1.1 and 0.2.0 are closed. 0.3.0 covers P9–P11 plus Claude Code
integration. 0.9.0 is the acceptance suite. 1.0.0 is publication.

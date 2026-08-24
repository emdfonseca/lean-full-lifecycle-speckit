# 0005 — The extension declares no Spec Kit hooks

Status: accepted
Date: 2026-08-24

## Context

The extension enforces four guarantees by telling an agent to do something:
the plan → gate → transition → read-back contract, the ratchet running after
verification, audit evidence being written, and the sensitive-data scan on
records. Instruction is a weak instrument, and Spec Kit appears to offer a
stronger one, so the omission needed to be a decision rather than an oversight.

Spec Kit has **two** mechanisms sharing the word, and the difference decides
this ADR.

`extension.yml` `hooks:` is agent instruction. `HookExecutor` never runs
anything: `format_hook_message` returns a string for display,
`check_hooks_for_event` documents itself as "designed to be called by AI agents
after core commands complete", and the whole executor region of
`specify_cli/extensions/__init__.py` contains no subprocess call. A hook is a
message an agent is asked to read.

`extension.yml` `events:` is different. `CANONICAL_EVENTS` in
`specify_cli/events.py` is `session_start`, `pre_tool_use`, `post_tool_use`,
`session_end`, `user_prompt_submit`, `stop`. The generated dispatcher
propagates a handler's exit code — `if result.returncode != 0: ... return
result.returncode` — so a `pre_tool_use` handler can refuse a call.

Adoption across the core pack, read from the installed CLI:

| extension | `hooks:` | `events:` |
|---|---|---|
| git | 18 | 0 |
| agent-context | 2 | 0 |
| assess | 0 | 0 |
| bug | 0 | 0 |
| github-lifecycle (ours) | 0 | 0 |

No core extension declares an event. The mechanism with enforcement power is
unused across the entire core pack.

## Decision

**This extension declares no `hooks:`.** Not for any of the four guarantees.

`events:` is a separate question and is not decided here. #99 spikes it.

## Rationale

**`hooks:` cannot refuse, and all four guarantees are refusals.** Each of them
is a statement about what must *not* happen: no transition without an approved
plan, no completion claim without the ratchet, no mutation without an audit
record, no record reaching review unscanned. A mechanism that formats a message
for an agent to read cannot enforce any of them. It would restate in a second
place what the command `.md` files already say, and a second copy drifts.

**Restating instruction as configuration makes enforcement look stronger than
it is.** That is the failure this repository has now corrected four times —
#88's dead policy, #89's unreachable redaction, #91's guard over a path that
did not exist, #93's rule nothing checked. Declaring 18 hooks the way `git`
does would produce a bundle that *reads* as though it enforces four guarantees
and enforces none of them.

**Two of four core extensions declare none.** `assess` and `bug` ship with
zero. Declaring none is an established shape, not an omission.

**The real enforcement points are already in code.** `transition_plan.py`
refuses an illegal edge, a stale plan, and a read-back mismatch — as #37 proved
against a real organization, where the read-back guard caught a backend that
could not read what it had just written. `validate_source.py` runs 23 checks.
Those refuse; a hook message cannot.

## Consequences

The four guarantees stay enforced where they are: in the scripts that refuse,
and in the command `.md` files that tell an agent what the command will refuse.

If enforcement should ever bind an agent's tool calls rather than its
instructions, `events: pre_tool_use` is the mechanism, and #99 establishes
whether it works and whether `specify bundle install` arms it — the CLI
suggests events may stay inert until `specify integration install|upgrade`
runs. That question is live because of #93, which found that nothing stops work
starting before an item is `In Progress`.

Revisit this ADR if #99 returns a working, installable event mechanism. The
decision here is about `hooks:` and does not survive as an argument against
`events:`.

## Correction to the spike that produced this

#81 argued the question should be answered "before P12's acceptance suite fixes
the current shape in place, because moving an enforcement point afterwards
means rewriting the tests that assert it".

Both halves are false. P12's suite shipped in #85, closed. And
`tooling/acceptance-scenarios.yml` contains no occurrence of "hook" — no
scenario asserts anything about them, so moving an enforcement point would
rewrite no test. The urgency was not real. The question was still worth
answering, for the reason at the top: an omission nobody decided is
indistinguishable from one nobody noticed.

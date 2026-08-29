---
description: Bootstrap, once — interview the person whose answers the product documents encode.
scripts:
  py: scripts/elicit.py
---

# GitHub Lifecycle Elicit

`bootstrap-policy.yml` declares under `product_elicitation` the questions whose
answers the seven product documents encode, the order to ask them in, and how
an answer is recorded.

```bash
{SCRIPT} --plan --format json
{SCRIPT} --check
{SCRIPT} --unresolved
```

`--plan` emits the questions and the rules for asking them. It asks nothing:
putting a question to a person is yours, and a script that claimed to do it
would report an interview it never ran. `--check` validates the record you
wrote. `--unresolved` lists the declines for the report's blockers line.

## What this is for

Before this existed, greenfield bootstrap wrote all seven documents from
`product_context` — one string, prompted as "Product idea and constraints" —
and asked nothing. Its four gates are approve/reject on content already
written, which is worse than no gate: a person who approved an artifact reads
it afterwards as agreed, and downstream work treats it as the project's stated
intent. A real run produced a constitution of eighteen principles and a
decision log recording three unrecovered product questions. Recording an open
question is not asking it.

## Conduct it as an interview

`--plan` prints the rules with the questions. They are the whole point and are
easy to lose under time pressure, so they are repeated here.

**One question at a time.** Ask, wait, then ask the next. Never show the queue
in advance — a person answering the second question has not seen the seventh,
and seeing it changes the second answer.

**Closed wherever the answers can be listed.** Two to five mutually exclusive
options in a table, one named as the recommendation with a line saying why.
Most of this interview should be a single keystroke per question.

**Open only where options would invent the product.** Two questions are open:
intent, and the domain vocabulary. A list of candidate intents is a list of
guesses about somebody else's product.

**A derived answer is still a question.** Where the product context implies an
answer, that turns an open question into a closed one whose recommended option
is the derived value, quoting the span it came from. It never removes the
question. A question skipped because the answer seemed obvious is the old
behaviour with an extra step.

**Later questions are built from earlier answers.** A question an earlier
answer settled is dropped visibly, recorded as `settled_by` that answer, not
dropped in silence.

## Nothing here blocks

A person who cannot answer says so, and the run continues. Blocking on a
question nobody can answer yet would make greenfield unusable, which is the
failure this must not trade for. What is guaranteed is that the question was
asked and that the silence stays visible.

A decline is recorded four times, and each one is load-bearing: with a reason
in the answer record; under `Open` in the decision log; as a sentence naming
the question unanswered in the section that wanted it; and in the bootstrap
report's `Unresolved blockers:` line, so the final gate shows a person the
total rather than one decline at a time.

## Report

State how many questions were asked, how many were answered, how many declined,
and which document sections are now written from an answer rather than from the
product context. Name each decline with its reason.

## Never

- Ask nothing because the product context looked complete. That is the defect.
- Show the remaining questions to make the interview feel shorter.
- Fill a section from a declined question. An invented answer is worse than an
  absent one, because the next reader believes it.
- Record `declined` without a reason. It is then indistinguishable from a
  question nobody reached.
- Edit the record to make `--check` pass. The record states what was asked;
  changing it to clear a check falsifies that.
- Call `/speckit.clarify` here. It aborts without a feature directory, reads
  `FEATURE_SPEC`, and writes into that spec's `## Clarifications`. Bootstrap has
  no feature and no spec.

---
description: Hold each measurable gate to the best it has ever done.
---

# GitHub Lifecycle Ratchet

```bash
python .specify/extensions/github-lifecycle/scripts/ratchet.py \
  --gate lint_or_static_analysis --measurement 41 \
  --produced-by "<commit or PR>" --write
```

`quality-gates.yml` names which gates ratchet and what each measures. Run it for
every ratcheted gate after verification, with the number that run produced.

## The four verdicts

**baseline_established** — there was no baseline. One is recorded now. **This is
not a pass.** A first run that reports a pass makes every later comparison
meaningless, because the baseline it silently recorded was never reviewed. Say
"a baseline was established" and do not say the gate passed.

**held** — the measurement matches the baseline. Nothing moves.

**improved** — the baseline moves to the new number. Requires `--produced-by`: a
baseline with no provenance cannot be argued with later.

**refused** — the measurement regressed. Report the gate, the baseline, and the
measurement. Do not re-run hoping for a different number.

## Loosening

`--loosen-to` moves a baseline the wrong way and requires an approved exception
naming that gate. The ratchet turns one way on its own; turning it back is a
decision somebody signs, and `exception-policy.yml` already records exactly
that — scope, owner, approver, and a review date.

## Never

- Report `baseline_established` as a pass.
- Move a baseline for a measurement you cannot attribute.
- Narrow what a gate measures to make a number look better. That is loosening
  the ratchet without saying so.
- Skip a gate declared ratcheted because it produced no number. It is refused
  for that reason: a gate that silently opts out is the one that regresses.

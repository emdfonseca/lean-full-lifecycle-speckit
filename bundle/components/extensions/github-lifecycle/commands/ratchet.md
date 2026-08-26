---
description: Hold each measurable gate to the best it has ever done.
scripts:
  py: scripts/ratchet.py
---

# GitHub Lifecycle Ratchet

```bash
{SCRIPT} \
  --gate lint_or_static_analysis --measurement 41 \
  --conditions "eslint, src/**" \
  --produced-by "<commit or PR>" --write
```

`quality-gates.yml` names which gates ratchet and what each measures. Run it for
every ratcheted gate after verification, with the number that run produced.

## `--conditions`: what the number covered

A baseline is compared only against a run under the same conditions. Say what
was measured: the coverage glob, the database backend, the analyser's rule set.

- A run that states no conditions is refused, and so is a baseline that records
  none. A number nobody can say what it covered cannot be compared against.
- Change what you measure and that run establishes its own baseline instead of
  being compared against a baseline of something else. Widening a coverage glob
  drops the percentage because the denominator grew; that is the project
  measuring more of itself, not a regression.
- Baselines under different conditions are held side by side under the gate.
  Narrowing what is measured therefore cannot raise the baseline the project is
  actually held to.

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
  the ratchet without saying so, and the recorded conditions are what makes it
  visible.
- Reuse a set of conditions that does not describe the run, to get a comparison
  against a baseline that measured something else.
- Skip a gate declared ratcheted because it produced no number. It is refused
  for that reason: a gate that silently opts out is the one that regresses.

# Recovering a workflow run that will not resume

A run whose process was killed without a signal Python could catch is left at
`status: running`, and `specify workflow resume` refuses it:

```
Error: Cannot resume run '49dd3313' with status 'running'.
```

The run is intact. Only the flag is wrong.

## Whether this is your situation

`^C` is **not** this. `specify_cli` catches `KeyboardInterrupt` and writes
`paused`, so an interrupted run resumes normally. What produces this state is a
death Python never observes:

| How the run ended | `state.json` | `resume` |
|---|---|---|
| `^C` (SIGINT) | `paused` | works |
| harness timeout, closed terminal, cancelled CI job | `running` | refuses |
| `kill -9` | `running` | refuses |

Check before editing anything:

```bash
cat .specify/workflows/runs/<run id>/state.json
ps -p "$(pgrep -f 'specify workflow' | head -1)" 2>/dev/null || echo "no run in progress"
```

**If a process really is running that workflow, stop here.** The flag is
correct and editing it would let two runs write the same state.

## The recovery

Set the status by hand, then resume:

```bash
python - <<'PY'
import json, pathlib
p = pathlib.Path(".specify/workflows/runs/<run id>/state.json")
state = json.loads(p.read_text())
assert state["status"] == "running", state["status"]
state["status"] = "paused"
p.write_text(json.dumps(state, indent=2))
PY

specify workflow resume <run id>
```

`resume` accepts `paused` and `failed`, so `paused` is what puts the run back
where it stopped, at `current_step_id`.

## What you are doing, and why it is not automated

You are editing another component's state file. `specify_cli` owns run state
and this bundle does not repair it: a script that did this on your behalf would
make a workaround permanent and would eventually do it while a run was genuinely
alive, which is the one case the flag exists to prevent.

Telling a dead run from a live one needs something the state does not record —
a pid, a heartbeat, or a lock the operating system releases on death. That is a
decision for `specify_cli`'s maintainers, and it is why the check above is a
person looking rather than a condition in a script.

## Avoiding it

Exposure is set by how long a step runs. The longest tier,
`artifact_synthesis`, is 1800s, and a harness or a person with less patience
than that produces this state. Steps are held to the tiers `step_timeouts` in
`bootstrap-policy.yml` declares, and `INV-STEP-TIMEOUT-TIER` reports any step
whose timeout is not one of them — so a step sitting on the longest tier has
been chosen for it rather than defaulted into it.

## Removing this page

Tracked as #123. When the upstream fix ships, `resume` will accept a run whose
owner is gone, and this page and the manual step both go with it.

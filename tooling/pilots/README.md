# Running a pilot

Four streams, one owner each. The gate at `0.9.0` asks for evidence **and** a
named owner, so a run with no owner is not a pilot however clean its record.

## Before

1. Pick the target. A real product, with real history. A synthetic repository
   cannot produce a legacy hotspot, and a brownfield pilot against one reports
   a pass it did not earn.
2. Copy `template.yml` to `docs/evidence/pilot-<stream>.md`. Fill in `stream`,
   `owner`, `target`, `started`.
3. Run with `--audit <path>` wherever a command accepts it. Without it
   `failed_github_operations` is `unmeasured`, not `held` — the record says no
   instrument was reading, rather than claiming nothing failed.

## During

Every entry takes a **verdict** and the **evidence** behind it. Never a
quantity: a number is the most confident way to state something nobody
instrumented, and `incorrect_or_out_of_scope_edits: 0` reads as measured when
it is a claim awaiting evidence.

| verdict | means |
|---|---|
| `held` | the property held. Say how it was checked, not that it was |
| `breached` | it did not. What happened, and what it cost |
| `observed` | recorded; the evidence carries the meaning, no pass or fail claimed |
| `not_applicable` | this stream does not do that thing |
| `unmeasured` | it applies, it was attempted, no instrument exists |
| `unrecorded` | nobody filled it in. Always refused |

`unmeasured` is the one worth getting right. `model_cost` is unmeasured in
every run so far, and that is a gap in the framework — recording it as one
keeps it visible instead of burying it as a pilot that fell short.

Record the **operator** entries as they happen. None can be reconstructed
afterwards.

The operator can be an agent. An agent driving a pilot observes its own
interventions and counts them, and `recorded_by: agent` is a fair answer.

Evidence is required for every verdict, `held` included. The verdict is the
part that invites a shrug; the evidence is what stops it. Three streams once
reported `0` for out-of-scope edits by three different ad-hoc methods, which is
the discipline this replaces.

When something fails, do not fix it in place. A pilot that fixes what it finds
stops being a measurement. Follow the loop:

```
requirement/test gap -> traceability update -> implementation
                     -> regression test -> rerun
```

File the finding, put its number in `failures[].tracked_by`, and carry on.

## After

```bash
python tooling/pilots/pilot_record.py --record docs/evidence/pilot-<stream>.md
```

It refuses an incomplete record rather than accepting one that looks finished.
A blank template reports 23 problems; that is deliberate, and
`test_the_shipped_template_does_not_pass_as_written` keeps it that way.

Then transition the pilot's Story and comment the record on it.

## What is already done

Stream 4, the GitHub sandbox organization, is delivered as #37 with emdfonseca
as named owner. It stood up a real organization, ran a full lifecycle through
the Issue Fields backend, and found two defects in the backend it was
verifying. Evidence: `docs/evidence/orgfields-round-trip.md`.

`plaincodelab` still carries the `Delivery Status` field and has no
repositories, so it is available for reuse.

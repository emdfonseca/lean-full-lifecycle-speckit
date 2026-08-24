# Running a pilot

Four streams, one owner each. The gate at `0.9.0` asks for evidence **and** a
named owner, so a run with no owner is not a pilot however good its numbers.

## Before

1. Pick the target. A real product, with real history. A synthetic repository
   cannot produce a legacy hotspot, and a brownfield pilot against one reports
   a pass it did not earn.
2. Copy `template.yml` to `docs/evidence/pilot-<stream>.md`. Fill in `stream`,
   `owner`, `target`, `started`.
3. Run with `--audit <path>` wherever a command accepts it. Without it
   `failed_github_operations` cannot be answered and the record must say so
   rather than report zero.

## During

Record the six **witnessed** metrics as they happen. They are observations
about a person working — how often you stepped in, whether the run needed
repair, what you made of it — and none can be reconstructed afterwards. That is
why `pilot_record.py` refuses a null for them and accepts one for the others.

Zero is a legitimate value. An unrecorded zero is not: write `0` and say that
none occurred.

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

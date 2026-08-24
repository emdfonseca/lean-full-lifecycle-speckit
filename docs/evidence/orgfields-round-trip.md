# Organization Issue Fields: verified against a real organization

Evidence for `REQ-GITHUB-ORGFIELDS-001`, collected 2026-08-24 against
`plaincodelab`, an organization with no repositories, so an organization-wide
Issue Field imposed nothing on existing work. The probe repository was deleted
afterwards; the field was left in place so this is re-runnable.

Recorded because the backend had never run against a real organization, and
the run found two defects in it. A requirement marked `implemented` on the
strength of tests written against a guessed payload shape is what this file
exists to prevent recurring.

## What the real API sends

`GET /repos/{owner}/{repo}/issues/{n}` returns, for a single-select
organization Issue Field:

```json
{"data_type":"single_select",
 "issue_field_id":46024252,
 "issue_field_name":"Delivery Status",
 "node_id":"IFSSV_kgDOAGxtYA",
 "single_select_option":{"color":"gray","id":80557703,"name":"Inbox"},
 "value":80557703}
```

Two things follow, and the backend had both wrong.

**The key is `issue_field_id`.** `IssueFieldBackend.read` matched on
`field_id` or `id`, neither of which the API sends. The loop never matched, so
every read returned `None`.

**`value` is the option id, not the option.** The readable name is under
`single_select_option.name`. Reading `value` returns `'80557703'` where the
caller expects `'Inbox'`. Projects v2 sends the option inline under `value`,
which is why one shared reader served both and served one of them wrongly.

## How it surfaced

The first write refused itself:

```
Conflict: read-back mismatch on issue #1 delivery_state: wrote 'Inbox', read None
```

The write had succeeded — the API held `Inbox`. The read could not see it.
The read-back guard turned a silent wrong answer into a loud refusal, which is
the whole reason it reads back rather than trusting the write.

## Round trip after the fix

```
null        -> Inbox         issue_exists
Inbox       -> Refining      refinement_started
Refining    -> Ready         readiness_verdict_ready
Ready       -> In Progress   owner_assigned, work_started
In Progress -> Output Done   acceptance_criteria_satisfied, required_ci_green,
                             applicable_security_green, convergence_clear,
                             operability_complete
```

Final state read back from the API:

```json
{"field":"Delivery Status","value":"Output Done"}
```

## Refusals, exercised against the real API

A stale plan:

```
Conflict: plan is stale: it observed 'Refining' but
plaincodelab/speckit-orgfields-probe#1 delivery_state is now 'In Progress'.
Re-plan rather than overwrite a change this plan did not account for.
```

An illegal edge:

```
PlanError: 'In Progress' -> 'Inbox' is not a legal transition.
From 'In Progress' the legal targets are ['Output Done'].
```

Backend selection needed no flag: `inspect_target` reported
`"backend": "issue-fields"` for a repository in an organization carrying the
field, and resolved all five option ids.

49 audited operations, every outcome `ok`.

## Creating the field

Not done by this bundle, and it must not be — `SEC-NO-ORG-SCHEMA-MUTATION`
asserts no script writes organization schema. The field was created by hand:

```
POST /orgs/{org}/issue-fields
{"name":"Delivery Status","data_type":"single_select",
 "options":[{"name":"Inbox","color":"gray","priority":1}, ...]}
```

`options`, not `single_select_options`, and every option requires `priority`.
Both were established by the API refusing the alternatives.

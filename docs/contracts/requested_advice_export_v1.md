# Requested advice export

`python -m scripts.export_requested_history` reads an **offline, consistent copy** of the
backend store. It exports completed plain one-week server answers for one entry and week,
across league pages and the standalone team page. It makes no network requests, runs no
solver and changes no input files. It is an operator export, not a public endpoint.

```sh
python -m scripts.export_requested_history \
  --store-snapshot /path/to/restored/store \
  --season 2026-27 --gameweek 10 --entry-id 2199732 \
  --deadline-utc 2026-11-06T18:30:00Z
```

Use the actual deadline from the relevant captured FPL event. JSON goes to stdout only
after all evidence passes validation. Refusals go to stderr with a nonzero exit code.
An empty `records` list means this snapshot has no eligible completed request; the command
does not create an answer for it.

## Evidence

The store already retains the three inputs: terminal jobs in `jobs/` and `jobs/archive/`,
request specifications in `specs/`, and immutable answer bytes in `cache/`. No additional
worker write or duplicate advice archive is needed. Keep these directories together when
backing up or restoring the store. Run the export against that restored copy, not against
a store being changed by API or worker processes.

The `requested_advice_export_v1` format contains the selected season, gameweek, entry,
deadline and a list of records. Each record has:

- `cache_key`: the complete answer identity, including source commit, configuration,
  projection handoff and any pinned public-team input fingerprint.
- `completed_at_utc`: the earliest successful terminal job time for that answer.
- `request`: its original `advice_job_spec_v1` specification.
- `response_json` and `response_sha256`: the exact original UTF-8 response and its digest.

Only `saf-puan`, window 1, without a rival or optional advice switches is selected.
The `public_entry` input identity is allowed. Other modes and client-side calculations
are not reclassified as plain server answers. The exporter checks the answer's identity
against its request and recalculates the cache address from the specification.

Queued, running and failed jobs are excluded even if their cache key has bytes. Completion
must precede the supplied deadline; the response envelope's older capture timestamp cannot
make a late calculation eligible. Job idempotency keys are not exported. Invalid or missing
evidence causes a refusal, without cache repair or fallback to an older result.

Distinct cache identities remain separate, including two releases using the same capture
and requests from different league pages. Nothing overwrites `member_advice_record_v2` or
`member_baseline_record_v1`. A successful result establishes that the backend made an answer
available; it does not prove that somebody viewed or followed it.

## Remaining integration

This export does not populate the site's settled history or calculate realized scores.
That consumer still needs an explicit choice among requested answers, the recorded player
mapping and settled-outcome join. It must retain the completion clock and request identity
instead of treating the export as a weekly page publication. No host installation or
scheduled export is part of this change.

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

## Site history

`scripts.build_requested_history` joins these answers to retained decision and outcome
captures and writes `history/requested/{entry_id}.json` under a selected league tree:

```sh
python -m scripts.build_requested_history \
  --store-snapshot /path/to/restored/store --snapshot-root /path/to/snapshots \
  --as-of-snapshot fpl-live-CAPTURE_ID --league-id 239 --entry-id 2199732 \
  --gameweek 10 --out-dir /path/to/preview/data/leagues/239
```

Repeat `--gameweek` to refresh several weeks. The actual captured FPL deadline must agree
between the decision and outcome calendars. The latest completed eligible answer is used;
equally recent answers that disagree are refused. The cached player codes and positions
are checked against the decision roster. Scoring shares the existing official autosub,
captain fallback, chip and transfer-hit rules, with no optimizer call. An unfinished or
unchecked event stays unsettled, and missing actual member points stay unknown.

The derived document uses `weekly_suggestion_history_v1` with the additive per-week fields
`advice_source: requested_server` and `request_cache_key`. It retains completion time in
`advice_generated_at_utc`. Previous requested weeks are preserved; newer outcomes can update
their scores, but an older capture or an incomplete store cannot erase them. Each output
file is replaced atomically only after validation.

The history page reads the requested file beside its existing weekly file. It adds requested
weeks that have no original plan, including an explicit `no_pre_deadline_record` row with
no advice evidence. Recorded plans and other refusal states retain precedence on overlap.
Requested rows are labelled “İstek üzerine” / “On request”. The original weekly files, immutable
advice archives and research horizon remain unchanged. Missing requested files are normal
for deployments that have not produced them yet; malformed evidence is not silently hidden.

## Preparing a snapshot from the running backend

```sh
python -m squadopt.platform.requested_history_snapshot \
  --store /path/to/backend/store --output-root /path/to/private/requested-history
```

This freezes live job metadata and the archived-job inventory under the queue's existing
lock. It then releases the lock before reading archived records or copying immutable
specifications and answers. A completion after that transaction is excluded even if its
second-resolution timestamp equals another completion's timestamp. The metadata transaction
refuses when its one-second work budget is exceeded. It never stops a service, recovers a
queue, quarantines a cache entry or calculates a plan.

Each successful copy is a verified `private_backup_v1` of an isolated staging subset. The
backup's `writers_stopped` declaration applies to that finished staging subset, not to the
running backend. Only completed plain one-week requests enter it; job idempotency keys are
removed. This is history evidence, not a complete queue restore. A failed copy keeps the
previous `latest.json` receipt; the receipt advances atomically after every output byte is
verified. Previous snapshots are kept so an in-progress run can resume against its original
input. Snapshot files and receipts stay private and must not be committed or served.

The command prints only the receipt path and manifest digest. `--group-readable` shares the
copy with the process's primary group (directories 0750, files 0640); run it with the weekly
service's group when that service must consume a root-owned backend's history. The default
creates new output roots and snapshots private to their owner. Source and output directories
must be disjoint.

## Weekly integration

The installed weekly command accepts `--requested-history-store /path/to/offline/store`.
The scheduled command can inherit the same path through `SQUADOPT_REQUESTED_HISTORY_STORE`
in its private environment file; an explicit command-line path takes precedence. This must
name a consistent, immutable offline snapshot, or the snapshot command's private `latest.json`
receipt. It must never name the backend's running store or a directory another process
refreshes in place. For a receipt, the weekly command checks the manifest digest and every
file before starting, then pins that exact backup in its journal. A resume verifies the pinned
backup even if `latest.json` has since advanced. For a directory, keep it at the same path for
resumes. The weekly command consumes the supplied source and does not stop backend writers.

When configured, the league stage refreshes requested history after the normal member
publication, for each listed league. Only members with requests or retained requested weeks
produce files; no new plan is calculated for this history. The store and retained captures
are journalled inputs, and generated history files are journalled outputs. Missing evidence,
incompatible existing history or changed inputs refuse the stage before publication. A
resume reuses the verified outputs and refuses a changed store.

Requested files join the protected publication identity, the release checks and the ready
bundle alongside existing history. The scoreboard stage records the final identity after
all league writes. The single-entry builder above produces an inspection artifact; use the
weekly integration when preparing a complete release tree, so the final identity covers it.

Without the option, existing requested files are retained unchanged. Running the snapshot
command under the host's service permissions, wiring its pre-run invocation and enabling
the setting remain rollout prerequisites; no snapshot producer is installed by importing it.

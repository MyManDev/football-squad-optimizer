# Crowd signal development-data audit

**Stop: `data_audit_failed`.** None of the 147 available development decision
folds has verified pre-deadline crowd capture provenance. The required minimum is
60. No candidate was pre-registered, no forecast or squad outcome was computed,
and no model gate was evaluated. This is an input-eligibility audit, not evidence
for or against an ownership-informed projection.

The [JSON record](crowd_signal_data_audit.json) was produced on 2026-11-26 by
[`experiments/crowd_signal_data_audit.py`](../experiments/crowd_signal_data_audit.py)
at repository commit `4a063bd51c0e09ccb687f8f0a16fb4f8011dc3d1`, on a branch
based on `95230aac536164ff73f205bc44033c1a97d110cd` (`origin/develop`).

## Named population and inputs

Only `2021-22`, `2022-23`, `2023-24` and `2024-25` were opened. The archive root
was the owner's existing local `data/raw/vaastav-fpl`, outside this worktree.
The audit does not call a panel loader or load a default season list.

For each season below, the full input path relative to that archive root is
`data/<season>/gws/merged_gw.csv`. The JSON names each exact path and its SHA-256.
Only headers were read from `data/<season>/players_raw.csv` and
`data/<season>/fixtures.csv`; no rows from those two files were read. The audit
also inventories metadata sidecar filenames inside those exact season
directories without opening sidecar contents. There are no JSON, JSONL, YAML or
YML sidecars there.

| Season | Archive rows | Distinct player/gameweeks | Gameweeks with rows | Candidate decision folds | Verified pre-deadline folds |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2021-22 | 25,447 | 23,230 | 38 | 37 | 0 |
| 2022-23 | 26,505 | 24,957 | 37 | 36 | 0 |
| 2023-24 | 29,725 | 28,742 | 38 | 37 | 0 |
| 2024-25 | 27,605 | 27,231 | 38 | 37 | 0 |
| Total | 109,282 | 104,160 | 151 | 147 | 0 |

Candidate folds count distinct observed gameweeks 2 through 38, not archive rows.
The archive contains no 2022-23 GW7 rows. Multiple fixture rows for one
player/gameweek are counted once for the distinct-player summary and once per
gameweek for the fold summary. The 147-fold count reproduces the declared
historical benchmark population's availability, without rebuilding predictions,
optimizing squads or reading its realized scores.

## Fields and timing

All four merged files have `selected`, `transfers_in`, `transfers_out` and
`transfers_balance`. All four fields are nonempty on every one of their 109,282
rows. Nonempty is a presence check, not a validation of the fields' economic
meaning or capture time. No merged file has a captaincy count or share column.

None of the merged files, players headers or fixture headers has a capture,
scrape, retrieval or deadline timestamp column. The players headers have
`selected_by_percent`, `transfers_in`, `transfers_out`, `transfers_in_event` and
`transfers_out_event`, but these files have no per-gameweek capture binding.
They cannot supply a historical sequence of decision-time crowd observations.

The fields that look time-related do not settle that gap:

- `kickoff_time` timestamps a match, not when ownership was observed or when a
  decision closed. The archive adapter already leaves `captured_at_utc` and
  `deadline_timestamp_utc` empty for historical fixtures
  (`src/squadopt/data/sources/vaastav.py`, `load_fixture_snapshot`).
- `news_added` belongs to player news, not the crowd-field capture.
- `modified` exists only in the 2024-25 merged file. Every one of its 27,605
  values is boolean (`true` or `false`), so none is a capture timestamp.
- Download time, filesystem modification time and a pinned archive commit do
  not establish the time at which an individual week's crowd fields were
  collected relative to that week's deadline.

The existing `benchmark_v2` measurement row explicitly calls historical
ownership timing unverified. This audit confirms that the locally available
development files do not repair that provenance. A directory-name inventory
of local immutable captures found only 2026 captures; no snapshot payload was
opened or used to expand the development population.

## Boundary and stop decision

No locked-season raw file or row was opened, loaded, hashed or printed. During
the required measurement-index lookup, adjacent historical holdout summary text
was returned as context. That text was not raw data, was not recomputed or used,
and subsequent index lookups were narrowed. No live capture payload, private
manager identity, bookmaker input or server was accessed.

The earlier rival, anchored and overlap scenario constructions remain closed;
no replacement construction is declared here. The missing evidence is at least
60 development folds with source-authenticated crowd capture timestamps and
their matching deadlines. Lagging an unverified archive field does not prove
that evidence. Future live captures cannot retrospectively repair these
development seasons. Acquiring admissible evidence would require a new scoped
task, followed by pre-registration before any candidate outcomes are computed.

The audit therefore stops before pre-registration and before measurement. No
change reaches the forecast, the live weekly pipeline or the published tree.

## Reproduction and checks

From this branch's worktree, using the existing environment's Python:

```powershell
python experiments/crowd_signal_data_audit.py --archive-root <local-archive-root> --output docs/crowd_signal_data_audit.json
python -m pytest experiments/test_crowd_signal_data_audit.py
python -m ruff check
python -m mypy experiments/crowd_signal_data_audit.py
python -m mypy
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
python -c 'from importlinter.cli import lint_imports; lint_imports()'
git diff --check
```

The synthetic tests check the explicit season boundary, duplicate-fixture fold
counting, boolean `modified` values, and refusal to silently accept a new timing
column or unreviewed metadata sidecar. No test opens the real archive.

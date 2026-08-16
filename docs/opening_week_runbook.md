# Opening Week Runbook (2026-27 GW1)

## Purpose

The first deadline of 2026-27 is the system's first live decision. This runbook fixes
the deadline-day sequence, the checks that decide whether the recommendation may be
acted on, and the honest states that are expected — so nothing is improvised against
the clock. Every command runs from the repository root on a clean, tested `develop`.

## Timeline

### T−1 day: readiness check

```powershell
.venv\Scripts\python -m pytest
.venv\Scripts\python -m ruff check --no-cache src tests scripts
.venv\Scripts\python -m mypy --strict src
```

All green or the live run does not happen from that tree. Confirm the operational
control in force (unless the fw10 holdout decision has been taken and promoted, the
control is `form_window=5, bench_weight=0.1, risk_aversion=0`).

### T−2h .. T−30min: capture

```powershell
.venv\Scripts\python -m scripts.capture_deadline_snapshot
```

- The capture is immutable and checksummed; note the printed `snapshot_id`.
- Capture early enough to leave time for a re-capture if the source hiccups; a later
  capture simply supersedes the earlier one (both are retained).

### After capture: recommend

```powershell
.venv\Scripts\python -m scripts.recommend_current_squad --output artifacts\live\gw1_report.txt
```

Omitted arguments resolve honestly: the most recent capture, the earliest deadline
still open at capture time, the season derived from the capture's own deadlines.

### Immediately after: verify the report before acting

1. **Provenance leads the report** — snapshot ID, capture time, report contract,
   feature contract. The model named must be the operational control
   (`projection_source: operational_control`); an unpromoted candidate on a live
   decision is a stop-everything defect.
2. **Availability is applied, not predicted** — unavailable players appear zeroed
   with the captured rule (`captured_availability_rule_v1`), never silently dropped.
3. **Squad sanity** — 15 players, budget respected, ≤3 per club, captain in the XI.
4. **Prior dependence is stated** — GW1 projections lean on carry-over and the
   opening price prior; the report says how much rests on the prior. High reliance is
   expected at GW1, not an error.

### Risk block: what GW1 must say

Do **not** pass `--risk-residuals` pointing at the development export. The correct
GW1 risk state is:

- no residual input → `not_requested` (the default, and the honest choice for GW1);
- if risk is requested anyway, only historical GW1 out-of-sample residuals under the
  control identity are valid evidence; the 147-fold development export starts at GW2
  and will produce `unavailable` with `unsupported_opening_gameweek` — that refusal is
  correct behavior, not a bug to work around.

### After the deadline: archive

Store together, outside the working tree: the `snapshot_id`, the report file, the
repository commit, and the command lines used. The replay path
(`--snapshot-id <id>`) must reproduce the same report from the same commit — spot-check
it once after the deadline:

```powershell
.venv\Scripts\python -m scripts.recommend_current_squad --snapshot-id <id> --output artifacts\live\gw1_replay.txt
```

## Contingencies

- **Source unreachable near the deadline:** use the latest good capture; the report's
  capture timestamp states exactly which information state the decision used.
- **Capture succeeds but recommendation errors:** the error is a domain message by
  design; do not patch live. Fall back to the newest previously verified report.
- **Late team news after capture:** re-capture and re-run; the newer snapshot wins.
  Never hand-edit a report.

## What this runbook does not authorize

Changing the operational control, running the fw10 locked holdout, or feeding
candidate artifacts into the live path. Those remain separate, deliberate decisions.

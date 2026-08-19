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

### After capture: decide (recommend + machine verification + ledger)

```powershell
.venv\Scripts\python -m scripts.run_gameweek_ops --phase decide
```

Omitted arguments resolve honestly: the most recent capture, the earliest deadline
still open at capture time, the season derived from the capture's own deadlines.
The decide phase applies every check below **as code** and exits 1 without recording
anything if any check fails; on success it freezes the decision (squad, projections,
report, checksums) into the season ledger under `data/ledger/<season>/gw<NN>/`.
(`scripts.recommend_current_squad` remains available for a report-only run that
touches no ledger.) The decision also records the season's published rules —
scoring, chips, transfer limits — read from the capture's `game_config` (`season_rules_v1`,
fingerprint in the ledger metadata), so a later reader knows which regime it was made
under; 2026-27 awards defensive-contribution points and values a goalkeeper's goal at ten,
neither of which the development seasons had.

### The checks the decide phase enforces

1. **Provenance leads the report** — snapshot ID, capture time, report contract,
   feature contract. The model named must be the operational control
   (`projection_source: operational_control`); an unpromoted candidate on a live
   decision is a stop-everything defect.
2. **Availability is applied, not predicted** — unavailable players appear zeroed
   with the captured rule (`captured_availability_rule_v1`), never silently dropped,
   and no unavailable player may be selected.
3. **Squad sanity** — 15 players, budget respected, ≤3 per club, captain in the XI,
   solver-proven optimality.
4. **Prior dependence is stated** — GW1 projections lean on carry-over and the
   opening price prior; the report says how much rests on the prior. High reliance is
   expected at GW1, not an error. (This one stays a human read of the report.)

### Risk block: what GW1 must say

Do **not** pass `--risk-residuals` pointing at the development export. The correct
GW1 risk state is:

- no residual input → `not_requested` (the default, and the honest choice for GW1);
- if risk is requested anyway, only historical GW1 out-of-sample residuals under the
  control identity are valid evidence; the 147-fold development export starts at GW2
  and will produce `unavailable` with `unsupported_opening_gameweek` — that refusal is
  correct behavior, not a bug to work around.

### After the deadline: archive

The ledger entry is the archive: `decision.json`, `projections.csv`, `report.txt`,
and `manifest.json` (per-file SHA-256) under `data/ledger/<season>/gw01/`. Note the
repository commit alongside it. The replay path (`--snapshot-id <id>`) must reproduce
the same report from the same commit — spot-check it once after the deadline:

```powershell
.venv\Scripts\python -m scripts.recommend_current_squad --snapshot-id <id> --output artifacts\live\gw1_replay.txt
```

### After the gameweek finishes: settle

Capture again (the later bootstrap carries realized `event_points`), then:

```powershell
.venv\Scripts\python -m scripts.run_gameweek_ops --phase settle --gameweek 1
```

This scores the frozen decision (starting XI plus captain double), records the
immutable outcome next to it, and regenerates the committed season summary
`docs/season_ledger_<season>.md`. Raw ledger entries stay local; only the summary
is committed.

## Gameweek 2 onward: decide from the held squad

Every deadline after the opening one starts from the squad the ledger holds — the
previous gameweek's recorded decision — and decides **transfers**, not a fresh squad.
The machine is the same script:

```powershell
.venv\Scripts\python -m scripts.capture_deadline_snapshot
.venv\Scripts\python -m scripts.run_gameweek_ops --phase decide --gameweek 2 `
    --in-season-projection handoffs\2026-27-gw02.json
```

What it needs, and refuses without:

- **The previous gameweek's decision in the ledger.** The held squad, bank, banked free
  transfers, purchase prices, and chips already played are read from `data/ledger/`;
  the opening entry supplies its own (purchase price = the price it projected at, bank =
  budget − cost, one free transfer). A gap (GW3 without GW2) is refused; record the
  missing week first, as a no-transfer roll if that is what happened.
- **A projection handoff** (`projection_handoff_v1`) from the model that produced it —
  the archive holds no played gameweek of the current season at deadline time, so the
  opening carry-over path cannot project GW2+. The file states season, gameweek, the
  capture it projected from, model name and version, and expected points per player
  code; identity, club, position, and price come from the capture; availability is
  applied by the live path as before. A handoff for another capture or gameweek is
  refused; an edited handoff fails its fingerprint.
- **A promoted in-season model version.** Verification requires the handoff's model
  version to be in `IN_SEASON_CONTROL_MODEL_VERSIONS` (`squadopt.live`); the list is
  empty until an in-season control clears its gates, and pinning a version there is the
  promotion decision, made in a reviewed change. Until then a GW2+ decision is refused
  at verification, not made from an unpromoted model.

The decision is the transfer planner with a **one-week horizon** — the weekly baseline
the planner measurements kept as control — under the season's published rules read
from the capture: free transfers banked to the cap, a hit per extra move, sales at the
sell price (purchase plus half of any rise, rounded down), the bank never negative.
Chips are **not timed by the planner** (a one-week horizon plays them at the first
opportunity; see `docs/season_chain_note.md`); play one by naming it:

```powershell
... --phase decide --gameweek 24 --in-season-projection ... --chip bboost
```

A named chip is refused outside its published window or if already played inside it.
The report gains a *Transfers* section (out, in, hits, free transfers, bank, chip); the
ledger entry gains a `transfers` block (`ledger_transfers_v1`) with the purchase prices
the next week sells at. Additional checks the decide phase enforces for a transfer
decision: what left was held, what came in was not, the squad after is held − out +
in, the bank after is not negative, hits equal paid transfers at the hit cost, a chip
played was offered, no selected player lacked a projection.

Settle is unchanged in use; the outcome nets the hits and counts a bench boost's bench
or a triple captain's third captain score, and the season summary shows transfers,
hits, chip, and net per gameweek.

## The season on a schedule: `run_season_tick`

Every step above can be chosen by the clock instead of by a person. One command,
safe to run every hour by hand, cron, or a workflow:

```powershell
.venv\Scripts\python -m scripts.run_season_tick            # do what is due
.venv\Scripts\python -m scripts.run_season_tick --dry-run  # say what is due, change nothing
```

It reads the captures held and the ledger and does, in order, whichever is due:
**capture** when the next deadline is within 3 h and no capture from inside that window
is held (or when a decided gameweek needs a post-gameweek capture to settle, polled at
most every 12 h after a 48 h grace); **decide** when an in-window capture exists and the
gameweek is undecided — GW1 from the capture alone, later gameweeks only if the
producer's handoff `data/handoffs/<season>-gwNN.json` is present, otherwise it waits and
names the path; **settle** when the latest capture marks a decided gameweek finished.
After a capture it re-plans once, so a deadline capture is decided in the same tick.
Everything is idempotent — a second tick in the same state does nothing — and every
step is the same code as the manual commands; the tick only chooses the moment. It
never plays a chip: run `run_gameweek_ops --phase decide --chip ...` by hand before the
tick would decide, and the tick then finds the decision recorded.

Every tick writes a structured run log — one JSON object per event (`tick.start`,
`tick.plan`, `tick.action.start/done/failed`, `ledger.decision.recorded`,
`ledger.outcome.recorded`, `tick.done`, or `tick.failed` / `tick.crashed` with the
traceback), tagged with a `run_id` — appended to `data/logs/season_tick/<date>.jsonl`
(`--log-root`, `-` disables the file). Exit codes: 0 done, 1 a known failure (data or
ledger error, stated), 2 an unexpected crash (never silent). Ledger writes are
crash-safe (staging directory, verified, one rename) and one writer per gameweek is
enforced with a lock file, so a tick that dies mid-write leaves nothing a later tick
refuses.

A missed deadline (closed with no decision) is reported, not decided late. Wiring the
tick to a scheduler (GitHub Actions cron, a small host) is the CI/app side's step; the
ledger and captures stay local by design, so a scheduled runner needs its own private
persistence for them.

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

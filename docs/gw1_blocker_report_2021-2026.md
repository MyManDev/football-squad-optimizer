# GW1 Evidence Blocker Report

- Reported by: prediction/data side (İbrahim)
- Date (UTC): 2026-08-16
- Repository commit: `1e5196e`
- Affected issues: #45, #38 (scope note only), opening-gameweek limitations register

## 1. Missing evidence

Historical opening-gameweek out-of-sample residuals under the live post-processing
identity `captured_availability_rule_v1`, for any season the archive covers.

Concretely, a GW1 residual row would need all of the following at the GW1 decision point,
and the archive supplies none of them:

- the player's availability state as published **before** the GW1 deadline;
- the player's price as published **before** the GW1 deadline;
- a capture timestamp proving both preceded that deadline;
- the published GW1 deadline itself.

The 147-fold development export remains valid for #38 recalibration. It begins at GW2 by
construction (`min_prior_gameweeks_in_season = 1`) and carries
`opening_gameweeks_included: false`. It is not convertible into opening-week evidence.

## 2. Affected seasons

| Season | GW1 status | Gap |
| --- | --- | --- |
| 2021-22 | absent | No pre-deadline capture. Roster snapshot carries end-of-season state (latest `news_added` 2022-05-21T14:00Z, after the season's final kickoff 2022-05-22T15:00Z). |
| 2022-23 | absent | Same. Latest `news_added` 2023-05-26T15:30Z vs final kickoff 2023-05-28T15:30Z. |
| 2023-24 | absent | Same. Latest `news_added` 2024-05-19T18:00Z vs final kickoff 2024-05-19T15:00Z. |
| 2024-25 | absent | Same. Latest `news_added` 2025-05-25T18:00Z vs final kickoff 2025-05-25T15:00Z. |
| 2025-26 | absent, and locked | Same shape (latest `news_added` 2026-05-24T21:30Z). Also the locked holdout; not read for this report beyond the file's own timestamp column. |

Inspected: `data/raw/vaastav-fpl/data/<season>/players_raw.csv` and
`gws/merged_gw.csv` at archive pin `8c97b2adb123863c3dd581e730f1360e89815ac2`.
No season is partially available. There is no per-gameweek roster file.

## 3. Unavailable provenance

| Field | Available? | What was inspected |
| --- | --- | --- |
| `captured_at_utc` | **No** | `players_raw.csv` carries no capture timestamp column. The capture time in section 2 is *inferred* from `max(news_added)`, which is a lower bound, not the file's own claim. |
| `deadline_timestamp_utc` | **No** | No archive file carries a deadline. `fixtures.csv` has `event` and `kickoff_time` only; `teams.csv` has neither. Deadlines exist only in the live source's events endpoint, which the archive does not mirror. |
| availability snapshot at GW1 | **No** | `merged_gw.csv` has no `status`, `news`, `chance_of_playing_*` or equivalent column in any of 2021-22…2024-25 — verified column-by-column. The only availability-bearing file is the season-end `players_raw.csv`. |
| price timing at GW1 | **No** | See section 4. |
| pre-deadline fixture calendar | **No** | The archive stores a rescheduled fixture under the gameweek it was eventually played in. `FIXTURE_STATUSES` deliberately has no postponed state (`src/squadopt/data/schema.py:328`). |

## 4. Why reconstruction would be leaky

**Reconstructing GW1 availability from the season-end roster.** The `status` field in
`players_raw.csv` describes the player at season end. In 2021-22 that is 134 players at
`u` (unavailable) and 51 at `i` (injured); in 2024-25, 167 and 59. Applying those states
at a GW1 decision would let the decision see nine months of subsequent transfers and
injuries. This is the largest possible leak in the dataset, not a marginal one.

**Reconstructing GW1 availability from realized minutes.** A player who recorded zero
minutes in GW1 was plausibly unavailable — but that reads the outcome the residual is
supposed to score. It also cannot distinguish "unavailable" from "fit but not selected",
which is precisely the distinction expected minutes is modelling.

**Treating the GW1 price as the deadline price.** `shift_price_to_deadline` replaces every
gameweek's price with the previous gameweek's, because the archive does not document
whether `value` is the deadline price or a post-gameweek price. GW1 has no previous
gameweek, so it keeps its own value — the one gameweek in the season whose price timing is
unproven.

The magnitude is bounded and worth stating rather than leaving open. Comparing GW1 and GW2
prices per player: 41/554 changed in 2021-22 (7.4%), 45/573 in 2022-23 (7.9%), 19/585 in
2023-24 (3.2%), 40/616 in 2024-25 (6.5%). So at most ~3–8% of players could carry a price
off by one 0.1 step. That is small in magnitude but **not random**: FPL prices rise after
good performances, so the affected players are disproportionately the ones that scored —
exactly the players a squad optimizer selects. A small biased error on the selected
population is worse than a larger unbiased one.

**Inferring the pre-deadline calendar.** Because postponed fixtures are stored under the
gameweek they were eventually played in, the GW1 fixture set as published before the GW1
deadline cannot be recovered. A blank or double gameweek created by a postponement is
invisible in hindsight.

## 5. Identity mismatch

`captured_availability_rule_v1` cannot be matched by any historical GW1 data.

The rule is defined over captured pre-deadline availability states — the `status` and
`chance_of_playing_this_round` fields as published before a deadline, with the doubtful
multiplier applied and every adjustment reported. No archive season carries those fields
at any pre-deadline instant. There is therefore no historical GW1 population over which
the rule could have been applied, and no way to produce residuals whose post-processing
identity equals the live one.

This alone forces `status=unavailable` via `model_mismatch`, independently of the
gameweek filter. The GW1 filter in `squadopt.live.risk` produces
`unsupported_opening_gameweek` for the same population, so both blockers describe the same
underlying gap from two directions.

## 6. Earliest valid future evidence date

We hold exactly one pre-deadline capture: `fpl-live-20260813T201143Z-55789a780186`, taken
2026-08-13T20:11:43Z for the 2026-27 opening deadline.

- **2026-08-21T17:30:00Z** — the 2026-27 GW1 deadline. A capture taken before this instant
  is the first valid GW1 decision-point evidence that will ever exist for this project.
- **≈2026-08-24** — after GW1 is played and settled, the first valid GW1 out-of-sample
  residual rows can be computed.

That yields **one fold, one season**. It is not a residual history. A usable GW1 residual
population accumulates forward at one fold per season and cannot be backfilled.

For that single fold to be valid, the capture must precede the deadline, be immutable and
checksummed, and carry availability, price, and the published deadline together. The
existing capture pipeline satisfies all four.

## 7. Required captures going forward

Per season, before every GW1 deadline, retained permanently:

- a pre-deadline snapshot with an explicit `captured_at_utc` in UTC;
- per-player `status` and `chance_of_playing_this_round`;
- per-player price at capture time;
- the published gameweek deadlines, so capture-before-deadline is provable rather than
  assumed;
- the fixture list as published at capture time, so a later reschedule cannot rewrite the
  calendar the decision actually faced.

Produced by `scripts/capture_deadline_snapshot.py`; retained under `data/snapshots/`
(git-ignored, checksummed, immutable). This is already the pipeline in use — the blocker
is historical, and the forward path is already closed.

## 8. Resulting system behavior

- A live GW1 risk report returns `status=unavailable` carrying
  `unsupported_opening_gameweek` (and `model_mismatch` where a residual history is supplied
  at all). No lower-tail number is printed. This is the current behaviour of
  `squadopt.live.risk` and it is correct.
- No GW2+ residual is relabeled as opening evidence. The 147-fold development export keeps
  `opening_gameweeks_included: false`.
- **#45 stays open** on structured `unavailable`. It can close on real evidence only, the
  earliest being the 2026-27 GW1 fold described in section 6 — and one fold is unlikely to
  support a calibrated interval, so realistically it closes after several seasons.
- **#38 is unaffected.** It consumes the GW2+ development export, which is valid for that
  purpose.
- The GW1 decision for 2026-08-21 proceeds normally. Only the risk line is withheld.

## Note on `docs/opening_backtest.md`

The opening-decision backtest (#76) uses the panel's GW1 `price_tenths`, which is the
unshifted value described in section 4. That does not invalidate the measurement — it is a
decision-level comparison, not a residual export, and it applies no availability rule — but
the price-timing caveat belongs on the record beside it. Added in this change.

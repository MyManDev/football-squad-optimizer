# Reading the fixture-group conformal measurement

Companion to [fixture_group_conformal.md](fixture_group_conformal.md) (contract
`fixture_group_conformal_v1`), the output of `scripts.run_fixture_group_conformal` on the
operational control's out-of-sample residual export (`oos_residual_export_v1`, table
SHA-256 `1ed41f94…`, 147 folds, 101,447 rows). It is the follow-up the uncertainty
layer's #38 decision named ([issue38_calibration_decision.md](issue38_calibration_decision.md)):
the operational calibration groups residuals by position only, and both measured regimes
undercover double gameweeks because a conformal radius fitted mostly on single-fixture rows
is too narrow for a player with two fixtures.

## Design

- Residual export joined to the published calendar with the same fixture bridge the
  recalibration study uses (`attach_fixture_features`); `fixture_group` is `single` (one
  fixture) or `double_plus` (two or more). Blank rows do not occur in the export (the
  archive records appearances) and would be excluded if they did.
- Chronological split by fold: the first 60% of folds (2021-22 GW2 … 2023-24 GW16, 88
  folds, 57,877 rows) calibrate; the last 40% (2023-24 GW17 … 2024-25 GW38, 59 folds,
  43,570 rows, of which 1,265 are doubles) are held out.
- Two calibrations on the same calibration rows, scored on the same held-out rows:
  **position-only** (the operational grouping, `ceil((n+1)·0.9)` order statistic of the
  absolute residual, as in `projection_uncertainty_v1`) and **position by fixture group**
  with a fallback to the position when a cell has fewer than 30 rows (no cell needed it:
  the smallest is GK doubles at 436).

## The numbers (held out, nominal 0.90)

| Population | Rows | Position-only | Position by fixture group |
| --- | ---: | ---: | ---: |
| overall | 43,570 | 0.918 (width 7.25) | 0.915 (width 6.99) |
| single | 42,305 | 0.920 (7.25) | 0.915 (6.90) |
| **double_plus** | 1,265 | **0.849** (7.24) | **0.901** (10.12) |
| DEF/double_plus | 412 | 0.854 | 0.927 |
| MID/double_plus | 558 | 0.839 | 0.885 |
| FWD/double_plus | 148 | 0.838 | 0.885 |
| GK/double_plus | 147 | 0.884 | 0.905 |

Radii: singles narrow by 0.2 for outfield positions (DEF 4.0 → 3.8, MID 3.4 → 3.2, FWD 4.0
→ 3.8; GK unchanged at 3.0); doubles widen to DEF 5.8, MID 4.6, FWD 5.8, GK 4.0.

## What it says

1. **The fixture axis repairs the double-gameweek undercoverage** the #38 study measured
   (0.83 / 0.80 there; 0.849 here on a different split) to 0.901 against nominal 0.90,
   at the cost of a 40% wider interval on those rows — which is what an honest interval on
   a two-fixture player looks like. Singles narrow slightly and stay above nominal.
   Overall coverage is unchanged and the mean width falls, because 97% of rows are singles.
2. **The mechanism is small and self-contained**: the same order-statistic rule, one more
   grouping key, a fallback that was never needed on the control's export. No model, no
   scale fit, no scenario component changes.
3. **What the live risk layer would gain** is an honest lower tail on exactly the weeks the
   season chain showed chips are worth playing on (bench boost and triple captain in
   doubles): the current position-only radius understates a double's spread by about a
   third.

## What follows

- A **declaration** for `projection_uncertainty_v2` — position by fixture group in
  `squadopt.uncertainty.calibration`, which today takes evaluation folds without a fixture
  count and would need the calendar attached at fit and apply time — and a re-fit of the
  frozen control calibration under it. This measurement is the evidence that declaration
  rests on; it does not make the change.
- The live risk layer's diagnostics should state the double-gameweek limit until then, as
  the #38 decision already asked.
- If #43 promotes, the same runner measures the candidate's export the same way.

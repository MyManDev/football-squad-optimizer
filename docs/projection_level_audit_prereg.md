# Projection level on the development folds: protocol

Status: pre-registered on 2026-09-19. Nothing under this protocol has been run. It changes no
projection, price or live control, and nothing in it is member-facing.

## Why

The live projection audit's first gameweek (gameweek 4, `docs/live_projection_audit.md`) put our
forecast low on the players who had been playing sixty minutes a gameweek and high on the players
the season had not yet seen, with the game's own forecast off in the opposite direction on the
regulars. One gameweek cannot say whether that is the model or the week: players inside a
gameweek share fixtures, and the live record will not hold six gameweeks before gameweek 9.

The development folds can say it now. The live model (`phase_c_control_components_v1`) is the
model whose out-of-fold predictions are the `phase_c_component_oof_v1` table: 101,447 player rows
over 147 chronological decisions in four seasons, every row predicted by a model that never saw
it. The locked 2025-26 holdout is not read.

## What is already on record, and what it does not answer

`phase_c_component_evaluation` scored that table in aggregate: appearance mean calibration bias
-0.0017, unconditional points MAE 1.090. Its appearance reliability bins are in the JSON record
and were never read for level:

| forecast appearance | rows | mean forecast | appeared |
| --- | ---: | ---: | ---: |
| under 0.1 | 39,347 | 0.076 | 0.041 |
| 0.2 to 0.3 | 4,539 | 0.247 | 0.411 |
| 0.3 to 0.4 | 3,189 | 0.346 | 0.458 |
| 0.8 to 0.9 | 14,602 | 0.868 | 0.855 |
| 0.9 and above | 14,628 | 0.926 | 0.929 |

So the aggregate is calibrated in the mean while the bottom bin, which is two fifths of all rows,
runs high and the bins between 0.2 and 0.5 run low. That is the same shape the live week showed
at the bottom. It says nothing about points: no record states whether the forecast of points is
level for regulars, for the rotation, or by the size of the forecast. No entry of
`measurements_index.md` and no module of `experiments/` reads the level of the points forecast
conditionally; the squad-level selection-optimism shift (`scenario_calibration_audit`) is a
different quantity, measured on selected squads and not on the player population.

Two records sit next to the "who plays" half of this question and neither answers it.
`rotation_oracle_ceiling` measured what a perfect signal for one kind of absence (a regular
rested) is worth as an exclusion before the solve: +1.1088 points per decision over the same
147 folds, interval [+0.1905, +1.7891], nothing changed in 92 of 147 decisions and 2021-22 the
other way. That is a ceiling on a flag, measured on squads; it does not say whether the
appearance forecast is level for regulars, and it bounds what a stage two "who plays"
candidate could be worth on that group, which its protocol will have to say.
`participation_calibration` read a start probability given appearance (bias +0.0049 pooled,
goalkeepers -0.0943) and left `p_appearance` deliberately unread, pointing at
`phase_c_component_evaluation` for it; the bins above are that record's, read for level here
for the first time.

## The table

The exporter (`scripts/export_component_oof.py`, v1 scope, default seasons) regenerates the table
on this machine. The record states the digest it got, and whether it equals the evaluated
`b05f10c3...`; an earlier independent reconstruction differed from the producer's bytes in eleven
cells at about 1e-9, so an unequal digest is recorded with the row count and the equality of the
exact keys, and the reading goes ahead on the regenerated table. The exporter's wall time is
reported, not estimated here.

## What will be read (stage one, descriptive)

The forecast is `control_expected_points`, the composition the live system uses. The outcome is
`points_target`. Rows whose `fixture_count` is zero are left out and counted.

1. **By prior minutes.** For every row, the minutes a gameweek the player had played in the same
   season strictly before the target gameweek, from the archive's per-gameweek minutes divided by
   the number of those gameweeks: none, under 30, 30 to 60, 60 and above, the same buckets as the
   live audit's reading 7. Only target gameweeks 4 and later are read, so that at least three
   gameweeks stand behind every prior. Per bucket: rows, forecast points summed, realized points
   summed, bias (realized minus forecast, per row), MAE.
2. **The same, decomposed.** Per bucket, on the component route only: `appearance_probability`
   summed against `appearance_target` summed; and, over the rows that appeared, the mean of
   `expected_points_if_appearance` against the mean of `points_target`. A level error is then
   either "who plays" or "what they score when they play", and the two are repaired differently.
3. **By the size of the forecast.** Fixed bands of `control_expected_points`: under 1.0, 1.0 to
   2.5, 2.5 to 4.0, 4.0 and above. The same numbers as reading 1.
4. **Where the solver buys.** Each decision's forty most highly forecast players per position:
   the same numbers, pooled.
5. Readings 1 to 4 per season as well as pooled.

Intervals are 90 per cent, by bootstrap over decisions (the 147 folds less the gameweeks before
4), 2,000 resamples, seed 0. A decision is the unit because players inside one share fixtures.

## What stage one may and may not say

- It may say that a bucket's bias interval excludes zero, pooled, and in how many of the four
  seasons the sign agrees.
- It names no repair as working. A level that is off is a finding; whether correcting it buys
  realized squad points is a separate question with its own gate, because a solver buys order
  inside a budget and a level correction that leaves the order alone may move nothing.
- The live gameweek 4 reading is not counted as a confirmation of anything found here, in either
  direction. It was the reason to look.

## Stage two, named now and not run under this document

If stage one finds a bucket whose pooled interval excludes zero with the same sign in at least
three of the four seasons, one candidate follows per fault, each under its own protocol with a
decision-level gate fixed before it runs (paired realized squad points against the control on the
same folds, `measurement_optimization_config()`):

- **Who plays:** a monotone recalibration of `appearance_probability`, fitted at every decision on
  earlier decisions only.
- **What they score when they play:** a level correction of `expected_points_if_appearance` by
  prior-minutes bucket, fitted the same way.

If stage one finds no such bucket, the record says so, the live audit keeps its fixed reading
dates (after gameweek 9 and 15), and no candidate is opened.

## The record

`docs/projection_level_audit.json` with its markdown twin and a row in `measurements_index.md`,
written by `scripts/measure_projection_level_audit.py`, which refuses to overwrite its record and
refuses the locked holdout before anything is read. The arithmetic lives in
`src/squadopt/evaluation/` with unit tests on hand-built tables; the runner holds the file access.

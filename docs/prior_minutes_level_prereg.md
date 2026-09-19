# A level correction by this season's minutes: protocol

Status: pre-registered on 2026-09-19, after stage one of `projection_level_audit_prereg.md` was
read and before anything below was fitted or solved. It changes no projection, price or live
control, and nothing in it is member-facing.

## What stage one found

Over the 139 development decisions from target gameweek 4 (`docs/projection_level_audit.md`),
bias as realized minus forecast, with 90 per cent intervals over decisions:

| minutes a gameweek this season, before the decision | rows | forecast | realized | bias |
| --- | ---: | ---: | ---: | --- |
| none | 30,659 | 4,735 | 1,023 | -0.121 [-0.130, -0.113] |
| under 30 | 28,315 | 22,153 | 22,837 | +0.024 [+0.004, +0.045] |
| 30 to 60 | 17,352 | 32,220 | 33,291 | +0.062 [+0.032, +0.094] |
| 60 and above | 19,588 | 56,199 | 58,614 | +0.123 [+0.084, +0.163] |

Every bucket carries its sign in four of four seasons, so stage two's rule opens a candidate. By
the size of the forecast the level is nearly flat. The forecast is honest about its own size and
blind to how much the player has played this season: a player the season has not seen is forecast
more than four times what he scores, mostly because he is forecast to appear, and a regular is
forecast about four per cent low, mostly in what he scores when he plays.

## Why one candidate and not the two stage one named

Stage one named a repair per fault (who plays; what they score when they play). Both faults are
indexed by the same thing, this season's minutes, and the solver reads one number, the composed
forecast. So the candidate corrects that number, by that index, and the decomposition keeps its
use for later: it says where a repair inside the model would go (the appearance model for the
unseen, the conditional points model for the regulars). A recalibration of the appearance
forecast by its own value, which stage one's text allowed, is not opened: the level by the size of
the forecast is flat, so there is nothing for it to fix.

## The candidate, `prior_minutes_level_v1`

For a decision `t` and a bucket `b` of the table above:

    factor(b, t) = sum of realized points / sum of forecast points

over every row of bucket `b` in the decisions strictly before `t`, in chronological order across
seasons, target gameweeks 4 and later only. The corrected forecast is the forecast times the
factor of the row's bucket.

- Fitted on earlier decisions only. No row is ever corrected by a factor its own decision, or any
  later one, contributed to.
- Until eight earlier decisions exist the factor is 1. For target gameweeks 1 to 3 the factor is
  1: fewer than three gameweeks stand behind the prior.
- The factor is clipped to [0, 2]. A thin-history row, which the table holds no component
  forecast for, keeps the direct control's forecast unchanged.
- No parameter is searched. The buckets are the live audit's, fixed before either reading.

## What is known to be compromised, said now

The index (this season's minutes) and its buckets were chosen after reading these same folds.
The factors are out of sample; the design is not. So a pass here is a development result, the same
standing `phase_c_component_evaluation` has, and two things stay untouched to check it later: the
locked 2025-26 holdout, and the live season, where the audit's reading 7 will say after gameweek 9
whether the corrected level holds.

## Gates, fixed now

On the development handoff `phase_c_component_oof_v1` as regenerated for stage one (table digest
`167f3e6a...`, roster digest equal to the evaluated one), all 147 decisions, base arm the
component forecast as it stands, candidate arm the corrected forecast, both solved with
`measurement_optimization_config()` and scored with the official autosub and vice-captain policy,
paired by decision.

1. **Level.** Out of sample, over the decisions where a factor other than 1 applied: in each of the
   four buckets the corrected bias is at most half the uncorrected bias in absolute value, and the
   pooled points MAE is not worse than uncorrected.
2. **Decisions.** The paired difference in realized squad points a gameweek, candidate minus base,
   with a 90 per cent block bootstrap interval (block length 4, 2,000 resamples, seed 0).

Verdicts:

- `decisions`: gate 1 passes and the interval of gate 2 lies above zero. The candidate may be
  proposed for the live projection, under the freeze rules, as its own change.
- `level_only`: gate 1 passes, the interval of gate 2 contains zero, and its mean is not below
  -0.25 points a gameweek. The forecast is more honest and the squads are not shown to be better.
  Whether the published number should then carry the correction is the owner's decision, not this
  protocol's.
- `failed`: anything else. The record says which gate, no threshold is moved, and the index is not
  swapped for another one on the same folds.

Also recorded, without a gate: the share of solves proven optimal per arm, selected starters with
zero minutes per arm, how many decisions chose a different squad, and the factors' paths over
time, so a reader can see whether they settle.

## What will not be claimed

- Nothing about the live season from this record.
- No statement that the model is fixed: a multiplicative factor repairs a level, it does not teach
  the model why a player stopped playing.
- Nothing member-facing, and no wording of chance anywhere a member reads.

## The record

`docs/prior_minutes_level.json` with its markdown twin and a row in `measurements_index.md`,
written by `scripts/measure_prior_minutes_level.py`, which refuses to overwrite its record and
refuses the locked holdout before anything is read. The arithmetic of the factor lives in
`src/squadopt/evaluation/` with unit tests, among them one that fails if any row's factor can see
its own decision.

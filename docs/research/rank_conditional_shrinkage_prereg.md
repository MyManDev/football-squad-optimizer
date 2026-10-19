# Rank-conditional shrinkage of expected points before the squad decision: protocol

Written before the measurement and not changed by it. The record that fulfils it is
`rank_conditional_shrinkage.json` with its Markdown twin `rank_conditional_shrinkage.md` in
this folder, written once by `scripts/measure_rank_conditional_shrinkage.py`. Nothing here
promotes anything or changes a product default. Measurement only.

## The question

The optimizer selects the players with the highest projected points, so the projections of
the selected players are biased upward: the winner's curse. `docs/selection_optimism.md`
measured it on the old control. Realized minus projected is -2.95 a selected starter and
-3.86 for the captain, and by projection rank within a fold's roster the bias is -3.5 for
the top five, -2.5 for ranks six to fifteen and about zero from rank sixteen on. The live
member path compensates with a planning hit cost of 8 against the game's 4, a blunt
instrument.

The question this protocol fixes: does a rank-conditional shrinkage of expected points,
fitted walk-forward on the gradient-boosting (GBM) out-of-fold table's own residuals and
applied before `optimize_squad`, raise the realized official score of the single-gameweek
squad decision against the same table unshrunk?

## The table

The GBM out-of-fold table of the Phase C v2 development scope, exported by
`python -m scripts.export_component_oof --development-scope v2 --estimator gradient_boosting`
from a clean tree: 2021-22 to 2025-26, 184 walk-forward folds, model version
`phase_c_control_components_gbm_v1`. Its comparison against the linear control is recorded
in [phase_c_gradient_boosting_comparison.md](phase_c_gradient_boosting_comparison.md), which
names the table digest `eae3e914…` and the roster digest `01d11113…`; the export is declared
byte-identical across runs at the same code, so the record pins the three digests it read
(table, roster, manifest) and reports whether the table and roster digests equal those.

2025-26 is read as development data under the v2 scope. It is never an unseen test. The
record carries `development_scope: v2` and `locked_holdout_accessed: true`, in the words the
repository already uses.

## The harness

`scripts/run_component_squad_calibration.py --phase-c-contract development_v2` is the
precedent and the loop is mirrored exactly:

1. the handoff is read through `read_phase_c_component_handoff(...,
   development_contract=phase_c_component_oof_development_v2)`;
2. the walk-forward ridge controls are built on the archive panel for the handoff's decision
   seasons with `build_walk_forward_folds(..., projection_builder=
   make_ridge_projection_builder(cross_season=CrossSeasonConfig()))`;
3. `prepare_phase_c_component_folds(handoff, controls, development_contract=...)` composes
   one `EvaluationFold` per fold on the complete roster. Its `expected_points` is the
   projection: `control_expected_points` (appearance probability times points given an
   appearance, at or above zero) on the component route, the ridge control's value on the
   direct-control route. This protocol reuses that composition and derives nothing else;
4. each arm's folds go through `evaluate_prepared_folds` with
   `measurement_optimization_config()` (deterministic budget 5.0, wall clock a cap) and
   `ScoringPolicy.OFFICIAL_AUTOSUB_CAPTAIN_V2`: `optimize_squad`, then
   `complete_optimization_decision`, then the official autosub and captain scorer against
   the fold's realized outcomes.

The arms differ only in the `expected_points` column handed to the optimizer. Roster,
prices, positions, realized outcomes, solver limits and scorer are identical.

## Population

Folds are ordered by `fold_id` (season, then zero-padded gameweek). The history of a fold is
every fold of the table strictly before it in that order, across seasons. A fold is a target
when its history holds at least eight folds; the first eight folds of 2021-22 (gw02 to gw09)
are burn-in and are excluded as targets, though their rows are history for later folds.
That gives 176 target folds over five seasons.

A fold whose decision in any arm has no solution (INFEASIBLE, or no incumbent inside the
budget) or loses its realized score is excluded from every arm, with the fold id and the
reason recorded. Both arms are compared on the same fold set. Nothing else excludes a fold:
a fold whose selected squad holds a direct-control-route player stays in, because the
projection on that route is the composition the harness already uses.

## Definitions

- **Projected**: the optimizer's `expected_points` per player, composed as in the harness.
- **Realized**: the player's official points in the fold, `points_target` where
  `appearance_target` is 1 and zero where it is 0 (a blank gameweek is zero). This is the
  `total_points` the harness scores decisions against.
- **Residual**: realized minus projected.
- **Rank**: within one fold, players ordered by projected descending over the fold's whole
  roster, ties broken by `player_id` ascending; the first player has rank 1.
- **Buckets by rank**, frozen: 1 to 5, 6 to 15, 16 to 30, 31 to 60, 61 to 120, 121 and
  beyond.
- **Position**: the roster's `position` (GK, DEF, MID, FWD).

## Control arm

`optimize_squad` on the unshrunk projection, completed and scored as above. The record
reports the solver status counts (proved OPTIMAL against FEASIBLE incumbents) through
`solver_record`.

## Arm A, primary: rank-conditional additive debias

For target fold t, take its history folds. In every history fold rank the players as
defined above and assign each row its bucket. For each bucket b, `r_b` is the mean residual
over all history rows in that bucket, pooled across history folds. The candidate projection
of a player in fold t with rank bucket b is `max(0, projected + r_b)`. Every history row
with a projected value contributes; a bucket with no history row (impossible at eight or
more folds of full rosters, stated for completeness) carries `r_b = 0`. Everything else is
the control.

## Arm B, secondary: linear shrinkage toward the position mean

On the history rows, per position, fit by ordinary least squares
`realized = a + lambda_pos * projected`. The candidate projection of a player in fold t is
`max(0, m_pos(t) + lambda_pos * (projected - m_pos(t)))`, where `m_pos(t)` is the mean
projected points of fold t's roster in that position. If the history projections of a
position have zero variance, `lambda_pos = 1` and the projection is unchanged. Arm B is
reported, not gated. It exists to show whether a gain is specific to the rank shape.

## Primary comparison

Arm A's realized official score minus the control's, paired per fold. The record reports the
mean, the median, wins, ties and losses, and the season means. The interval is the
repository helper's 90% season-aware moving-block bootstrap
(`squadopt.evaluation.statistics.season_aware_moving_block_interval`): blocks of four
consecutive folds within a season, 2,000 resamples, base seed 0, candidate id
`rank_conditional_shrinkage_v1`. The helper derives its stream from the base seed and the
candidate id, and the record quotes the helper's interval, not another implementation of it.
Arm B minus control is reported the same way with candidate id
`rank_conditional_shrinkage_v1_position`.

## Gate

The noise floor is 1.5 points a gameweek: an effect smaller than that is not certified.
Arm A is **certified** only if all three hold:

1. its mean paired gain over the control is at least +1.5 points a gameweek;
2. the 90% interval excludes zero (its lower end is above zero);
3. its season mean is negative in at most one of the five seasons.

Otherwise the verdict is **measured, not certified**, reported as measured, with no
softening and no re-run. The record's first sentence states the verdict.

## Diagnostics, reported not gated

Per arm (control, A, B):

- the mean of projected minus realized over the selected eleven starters and over the
  captain, under the arm's own projection and under the unshrunk projection of the same
  players: the selection gap the correction is meant to close;
- the mean of each `r_b` over the target folds, and its value at the first and last target
  fold (Arm A); the mean `lambda_pos` per position (Arm B);
- the overlap of the selected fifteen and of the starting eleven with the control's;
- the hit of blanks: starters with zero realized minutes, autosub points and vice-captain
  recoveries;
- the solver status counts.

## What a pass licenses

A second pull request that pins Arm A's rule as a named projection adjustment version on the
live in-season path, behind an explicit flag that defaults off, prepared on a pushed branch
and opened by the owner after reviewing the record. A fail licenses nothing but the record.

## What is not measured

Transfer decisions and multi-week plans; the historical ridge control as an arm; any
member's squad; Top100 evidence; 2025-26 as a test; any bucket edge, shrinkage form, floor or
seed other than the ones written here.

Scope statement added on 2026-10-17 at the owner's request on the pull request, after the
measurement and without changing any gate, grid, population, seed or budget above: the
planning hit-cost arms (planning hit cost 4, with and without the transfer cap, on the season
chain with transfers) and buckets by the four position groups are deferred to a named
follow-up pre-registration, `docs/research/rank_conditional_shrinkage_chain_prereg.md`, which
is not written here.

## Record

`docs/research/rank_conditional_shrinkage.json` and its Markdown twin, written once by the
runner from a clean tree, naming this protocol, the commit that ran, the archive commit, the
three digests of the GBM artifacts, the machine and solver versions, the start and finish
times, and the per-fold table's sha256 under `artifacts/rank_conditional_shrinkage/`. A row
in `docs/measurements_index.md` links the record. No pilot was run before this protocol was
committed.

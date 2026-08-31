# Phase 2 projection-conditional return-shape diagnostic

Status: pre-registered exploratory development reuse. This study is not independent
confirmation, is not a promotion gate, and may not read the locked 2025-26 holdout.

## Question

The preceding diagnostics found that the selected-XI downside miss is concentrated among
players who completed at least 60 minutes. Direct raw residual pools did not repair the miss,
and removing the canonical decomposition made the conditional tail thinner rather than wider.
The remaining narrow hypothesis is that a completed player's discrete return distribution
changes with the projection available at the decision timestamp and, possibly, with recent
history.

This study asks two ordered questions:

1. does conditioning completed-appearance returns on the pre-decision expected-points band
   improve out-of-fold return-state calibration over position alone;
2. after that comparison, does restricting the same conditional history to the most recent
   eight completed folds add a further improvement?

It diagnoses an outcome component. Realized minutes are never proposed as a live feature, and
no result directly authorizes a production scenario change.

## Frozen population and chronology

The fold universe, residual export, projection model, optimizer decision, selected XI,
scenario matrix, scenario count, seed, frozen shift and chronological history boundary are
exactly those in `phase2_conditional_marginal_shape`. Only selected starters whose realized
minutes are at least 60 enter the target population. Historical source rows are also restricted
to completed appearances for this diagnostic.

Roles remain:

- 2021-22 and 2022-23: screening;
- 2023-24: descriptive validation classification;
- 2024-25: already observed development sensitivity;
- 2025-26: locked and forbidden at the loader boundary.

Development folds use only their declared `prior_fold_ids`. For 2024-25, both full-history and
recent-history arms use the same history frozen at the end of 2023-24; the history does not
advance inside 2024-25. The recent arm takes the last eight distinct fold identifiers in
chronological order from the otherwise allowed history. A target outcome never enters its own
source history.

The recorded 2024-25 full-score control replay and the completed-appearance population must
reconcile with the prior artifacts to `1e-12` before a new artifact may be written.

## Fixed states and projection bands

Realized total points are assigned to exactly one of four states:

- `points_le_1`: at most 1 point;
- `points_2_3`: 2 or 3 points;
- `points_4_5`: 4 or 5 points;
- `points_ge_6`: at least 6 points.

Points must be finite integer values. Expected points must be finite and non-negative. The five
expected-points bands are fixed as `<3`, `[3,4)`, `[4,5)`, `[5,6)` and `>=6`; no edge may be
selected after seeing the result.

## Three ordered arms

For each target starter, estimate the four state probabilities from exact pre-fold history:

1. `position_full`: same-position completed appearances over the full allowed history;
2. `position_x_expected_points_full`: same position and expected-points band over the full
   allowed history;
3. `position_x_expected_points_recent8`: same position and expected-points band over the last
   eight allowed folds.

Every source needs at least 30 observations. The two conditional arms use one frozen fallback
order: exact position-band cell, same-position union of the exact and immediately adjacent
band or bands, position, then pooled completed appearances. The position arm uses position and
then pooled. The selected level and observation count are recorded for every target. A pooled
source below 30 observations, a non-finite value or an empty source refuses the fold.

The same source also supplies an empirical residual q25 using NumPy's linear quantile. Its
expected downside rate is the fraction strictly below the threshold, preserving discrete ties;
the realized event uses the same strict comparison.

## Primary measurements

The primary score is the four-class Brier score. It is calculated per target row, averaged
within each fold, and then averaged across folds so a fold is the unit of comparison. Paired
differences are:

- `delta_projection = Brier(position_x_expected_points_full) - Brier(position_full)`;
- `delta_recent = Brier(position_x_expected_points_recent8) -
  Brier(position_x_expected_points_full)`.

Intervals are paired fold-cluster bootstraps with 5,000 resamples, 90% confidence and seed 0.
An arm improves only when the interval's upper bound is strictly below zero.

For tail non-regression, each arm records the absolute per-fold q25 calibration gap. A candidate
arm is non-regressing only when the paired interval for
`absolute gap(candidate) - absolute gap(control)` has an upper bound at or below zero.

Projection localization is measured under the `position_full` probabilities. For the ordinary
return state `{2,3}`, compute each fold's observed-minus-predicted gap separately for target
rows with expected points `<5` and `>=5`, then subtract low from high. Projection localization
requires the paired 90% interval's lower bound to be strictly above zero.

## Support and descriptive outputs

The validation classification requires at least 30 folds, at least 50 target rows and 20 unique
players in each of the `<5` and `>=5` groups, and direct exact position-band coverage of at
least 80% for both conditional arms. Otherwise it is `diagnostic_inconclusive`.

For every season and pooled, report arm-level fold and row counts, mean Brier score, paired
comparisons, q25 gaps, source/fallback counts and direct-cell coverage. Report the five-by-four
observed and predicted state table, top-player row share and leave-top-player-out sign
sensitivity as diagnostics only. No cell, player or season is allowed to select a model.

## Descriptive classification

Only 2023-24 assigns one label:

- `projection_and_recency_signal`: support passes, projection is localized, both ordered Brier
  comparisons improve, and both conditional arms pass q25 non-regression;
- `projection_conditional_shape_candidate`: support passes, projection is localized, the full
  conditional arm improves and passes q25 non-regression, while the recent arm does not improve;
- `recency_weighted_shape_candidate`: support passes, the full conditional arm does not improve,
  the recent arm improves and passes q25 non-regression;
- `conditional_shape_not_localized`: support passes but none of the preceding rules holds;
- `diagnostic_inconclusive`: a support, reconciliation or required-metric condition fails.

The first label requires a separate combined-candidate preregistration. The second may open a
shape-only expected-points candidate study; the third may open a separate recency-only study.
No candidate is implemented until this artifact has been written and its exact classification
has selected one branch. A negative or inconclusive result is final for this study and is not
followed by alternate bands, state definitions, history lengths or support thresholds.

## Interpretation limits

Completed appearance is known only after the outcome. A positive result therefore identifies a
completed-appearance return component; a deployable whole-player distribution would still need
a separately specified pre-deadline appearance mixture. This study changes no generator,
projection, optimization, publication or evidence status, publishes no probability, and does
not access or infer the locked holdout.

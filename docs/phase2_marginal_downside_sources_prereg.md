# Phase 2 marginal-downside source diagnostic

Status: pre-registered exploratory development reuse. This study is not independent
confirmation, is not a promotion gate, and may not read the locked 2025-26 holdout.

## Why this follows the dependence diagnostic

The selected-XI dependence diagnostic found a large marginal miss before dependence could be
identified: on 2023-24 validation, starters fell below their own scenario-marginal q25 at a
rate of 0.4816 against 0.2500. The all-pair statistic cannot separate that miss because, for a
fixed XI, it is mechanically determined by the number of downside starters. No dependence
model may be selected until the marginal miss is explained.

This study asks which of three observable sources carries the excess downside:

1. no appearance (`minutes == 0`);
2. partial appearance (`1 <= minutes < 60`);
3. a full appearance (`minutes >= 60`), where the remaining miss is points performance rather
   than failure to complete the appearance threshold.

It also measures a model fact already visible in code: the canonical generator centres every
hierarchical shock, and `player_location_shrinkage` is frozen at `None`, so a selected player's
historical mean residual is deliberately omitted from the scenario location. The study asks
whether those pre-fold player means are negative and predictive; it does not turn the option on.

## Frozen inputs and population

The fold universe, model, projection, optimizer decision, selected XI, residual export,
scenario matrix, q25 downside definition, scenario count, seed and history boundary are exactly
those in `phase2_downside_dependence`. The same control replay must reproduce the recorded
2024-25 full-score PIT and S2 values to `1e-12` before an artifact may be written.

Roles remain:

- 2021-22 and 2022-23: screening;
- 2023-24: descriptive validation classification;
- 2024-25: labelled development sensitivity already observed;
- 2025-26: locked and forbidden at the loader boundary.

No availability field of ambiguous historical timing is read. `minutes` and `total_points` are
post-outcome fields used only after the decision and scenario are frozen.

## Per-starter record

For each of the fixed XI's eleven starters in each fold, record:

- player, team, position and fold identifiers;
- expected points and realized points;
- realized minutes;
- canonical scenario-marginal q25 residual threshold;
- scenario-expected downside-event rate under that threshold;
- realized downside-event indicator using the same strict comparison;
- downside excess contribution: indicator minus scenario-expected rate;
- number and mean of that player's residuals in the exact pre-fold history supplied to the
  generator;
- the omitted player-location mean when history exists; missing stays missing, never zero.

The pre-fold history is the only source for the location measurement. Evaluation-season outcomes
never enter their own history.

## Summaries

For every season and the pooled population, report by minute bucket (`0`, `1-59`, `60+`):

- starter rows and share;
- realized and scenario-expected downside counts and rates;
- total downside excess contribution;
- share of the population's positive excess, when total excess is positive;
- mean expected points, realized points and residual.

For omitted player location, report coverage, mean, negative share, correlation with the later
realized residual, and the same summaries for downside and non-downside rows. Bootstrap intervals
are fold-clustered at 5,000 resamples, 90%, seed 0 and diagnostic only.

## Descriptive classification

Only 2023-24 assigns one label. Let each bucket's contribution be the sum of
`realized downside indicator - scenario-expected downside rate`.

- `appearance_minutes_dominant`: the combined `0` and `1-59` contribution is positive and
  strictly larger than the `60+` contribution.
- `full_appearance_performance_dominant`: the `60+` contribution is positive and at least as
  large as the combined low-minute contribution.
- `marginal_sources_mixed`: both sides are non-positive, a required minutes field is missing,
  or fewer than 30 folds are available.

This is an accounting classification, not a causal or promotion claim. The 2024-25 sensitivity
cannot change it. Omitted player location is reported beside it but cannot change it because
turning a historical mean into a scenario correction requires a separate shrinkage contract.

## Interpretation limits

An appearance-dominant result sends the next candidate toward an explicit appearance/minutes
mixture. A full-appearance result sends it toward residual marginal shape or projection-rate
error. A negative omitted player mean identifies a location candidate but selects no shrinkage.
No result changes prediction, scenario generation, optimization, publication or holdout status.

# Phase 2 selected-XI downside-dependence diagnostic

Status: pre-registered development diagnostic. This study is exploratory reuse of
development outcomes, is not independent confirmation, promotes nothing, and may not read the
locked 2025-26 holdout.

## Question

The recorded squad calibration is centred but too thin below: S1 passed while the realized
score fell below its scenario q10 in 8 of 37 evaluation folds. A global dispersion scale was
not stable across seasons, the recorded all-player common-week component was weak, and removing
the captain's extra copy left the 2023-24 and 2024-25 S2 failures in place.

This study asks one narrower question:

> Does the canonical scenario generator under-represent several members of the selected XI
> falling below their own marginal downside threshold together?

The distinction matters. Too many individual downside events is a marginal problem. The right
number of individual events but too many simultaneous pairs is a dependence problem. This
study measures those separately before any scenario-generation change is proposed.

## Frozen population and inputs

The study reuses the exact Phase 2 fold construction, model, projections, optimizer settings,
selected squad, starting XI, captain, residual export, frozen history, generator settings,
scenario seed and scenario count. It does not re-optimize after observing an outcome and does
not alter the captain multiplier, the frozen score shift, or any scenario value.

The declared seasons retain the tail diagnostic's roles:

- 2021-22 and 2022-23: screening;
- 2023-24: validation for the diagnostic classification;
- 2024-25: labelled development sensitivity, already observed before this study;
- 2025-26: locked confirmation holdout, forbidden at every loader boundary.

The 2024-25 control full-score PIT and below-q10 rate must reproduce the recorded Phase 2
artifact to `1e-12` before the diagnostic may write an artifact. A mismatch is drift, not a new
result, and the run stops.

## Unit of analysis

Each fold keeps the optimizer's fixed starting XI. The captain appears once, like every other
starter; the extra captain scoring copy is deliberately absent because the preceding ablation
already measured it. Bench players are absent. A fold must contain exactly eleven distinct
starters, all present in projections, scenarios and realized points, or it is refused.

For starter `i` in fold `f`:

- scenario residual: `scenario_points_i - expected_points_i`;
- realized residual: `realized_points_i - expected_points_i`;
- marginal downside threshold: the linear empirical q25 of that player's canonical scenario
  residuals;
- downside event: residual strictly below that threshold.

The lower quartile is fixed before execution. It gives roughly 2.75 expected downside events
among eleven starters and therefore enough resolution to study simultaneous events with the
pre-registered 200 scenarios. No alternate quantile is run.

## Per-fold measurements

Let `K` be the number of starters in downside and let `J = choose(K, 2) / choose(11, 2)` be
the fraction of starter pairs simultaneously in downside. The study records:

- realized and scenario-mean marginal downside rate, `K / 11`;
- realized and scenario-mean all-pair joint downside rate, `J`;
- the same joint rate split into same-team and different-team starter pairs;
- paired realized-minus-scenario gaps for every rate;
- the realized count's discrete mid-PIT within the scenario count distribution:
  `P(K_s < K_realized) + 0.5 P(K_s = K_realized)`;
- whether the realized count is strictly above the scenario distribution's linear q90;
- the canonical scenario covariance contribution to XI-total variance,
  `Var(sum residuals) - sum Var(player residual)`; this is descriptive only;
- whether the fold was a recorded full-score below-q10 event.

Missing same-team pairs are recorded as unavailable for that fold, never as zero. No player,
team or fixture join is invented.

## Population summaries

For each season and for the pooled development population the study reports fold means of the
realized rates, scenario-expected rates and paired gaps; mean count mid-PIT; above-q90 count;
and the same summaries separately for recorded full-score below-q10 folds and the rest.

Uncertainty is a paired, fold-cluster bootstrap of the mean gaps at 5,000 resamples, 90%
confidence and seed 0. It is diagnostic, does not alter the Phase 2 calibration verdict and
cannot promote a model.

## Diagnostic classification

Only 2023-24 assigns one descriptive classification. It is explicitly not a gate or an
independent confirmation.

- `joint_downside_underrepresented`: the 90% paired-bootstrap interval for the all-pair joint
  downside gap is strictly above zero while the interval for the marginal downside-rate gap
  contains zero.
- `marginal_and_joint_downside_miss`: the marginal-gap interval excludes zero and the joint
  gap is positive. This does not attribute the joint gap to dependence because wrong
  marginals can create it.
- `no_joint_downside_evidence`: the all-pair joint-gap interval is not strictly above zero.
- `diagnostic_inconclusive`: fewer than 30 validation folds, a required input is missing, or a
  declared metric cannot be computed.

Same-team and different-team intervals describe where a measured joint gap sits but do not
change this classification. The 2024-25 sensitivity cannot change it.

## Interpretation limits

A `joint_downside_underrepresented` result localizes a missing selected-XI dependence signal;
it does not select a copula, block bootstrap, latent shock or scale. A
`marginal_and_joint_downside_miss` result requires marginal calibration to be separated before
claiming dependence. A `no_joint_downside_evidence` result sends the investigation back to
downside magnitude or tail shape rather than correlation.

No result changes the generator, publishes a probability, opens the locked holdout, or
authorizes another parameter sweep. A structural candidate requires a separate pre-registration
committed after this diagnostic is recorded.

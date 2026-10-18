# Phase C points-only gradient-boosting candidate: declaration and comparison method

This note declares the fourth Phase C v2 *development* candidate and the comparison it is
measured by. It is written before the measurement and is not changed by it. It changes
nothing in the frozen Phase C v1 contract, its artifacts or its evaluation protocol, and
it does not promote anything: promotion is a separate, reviewed change that pins a model
version in `src/squadopt/live/recommendation.py`.

## Why this candidate

The gradient-boosting estimator pair (`phase_c_gradient_boosting_method.md`) and the v2
feature contract (`phase_c_feature_contract_v2_method.md`) were both preferred under the
points-MAE rule and both scored fewer realized squad points than the linear components on
the 147 frozen decision folds. The decision-level readings recorded beside those rules
asked which part of the composition the solver reads (expected points equals appearance
probability times expected points given an appearance) carries the loss. Research probes
that recomposed the exported tables placed it in the boosted appearance probability: the
linear appearance with the boosted conditional points scored the most realized points of
every composition tried (+5.36 a gameweek against the ridge control, against +4.89 for the
linear components and +4.14 for the boosted pair; paired against the linear components
+0.47, 90% interval [-1.18, +2.23]), and the reverse mix was as poor as the boosted pair.
Those probes were recompositions of already-exported tables, not a fitted arm, and their
interval crossed zero. This declaration fits the composition as an arm of its own, so the
repository's own protocol measures it, at the player level and at the decision level.

## The two arms

Both arms use the same features (`phase_c_component_form_window_v1`), the same targets
(`phase_c_component_targets_v1`), the same rows, the same routes (a row without complete
features takes `direct_control`; a blank gameweek is zero), the same folds and the same
walk-forward cutoff: every fold trains only on rows strictly before its own gameweek, under
the v2 development scope (2021-22 to 2025-26, 2025-26 read as development data, never as an
unseen test). Equal weighting on both arms.

- **A, control:** the linear fit, model version `phase_c_control_components_v1`:
  `StandardScaler` + `LogisticRegression(C=1.0)` for appearance; `StandardScaler` +
  `Ridge(alpha=1.0)` for minutes and for points given an appearance.
- **B, candidate:** the points-only boosted fit, model version
  `phase_c_control_components_gbm_points_v1`,
  `ComponentModelConfig(estimator="gradient_boosting_points")`: the control's appearance
  and minutes estimators unchanged, and `HistGradientBoostingRegressor` (squared error) for
  points given an appearance with the constants already declared for the boosted pair:
  `learning_rate=0.05`, `max_iter=300`, `max_leaf_nodes=31`, `min_samples_leaf=100`,
  `l2_regularization=1.0`, `early_stopping=False`, `random_state=0`. No other value is
  tried and none is changed after the results are seen. The candidate refuses season-age
  weighting, so the arm space stays at the declared pairs.

The predictions keep the control's bounds: appearance in [0, 1], minutes in
[0, 90 x fixtures], public points at or above zero, and `control_expected_points` equal to
appearance times points.

## The fixed comparison

`scripts.export_component_oof --development-scope v2 --season-weighting equal` writes the
control table `phase_c_component_oof_development_v2_equal`; adding
`--estimator gradient_boosting_points` writes
`phase_c_component_oof_development_v2_equal_gradient_boosting_points`, whose manifest
records the estimator and its constants and whose per-fold records carry `estimator`. Both
must come from the same commit of a clean tree.

`scripts.compare_component_oof_development --candidate-arm gradient_boosting_points` reads
both through the development reader, refuses arms that are not one paired measurement
(same commit, same rows, same targets, same coverage), scores each with
`evaluate_component_oof`, and applies the acceptance rule of the v2 method unchanged: the
candidate is preferred only if (i) its 2025-26 points MAE is lower than the control's,
(ii) the 90% season-aware moving-block interval of the per-fold paired differences
(control MAE minus candidate MAE) on 2025-26 lies entirely above zero, and (iii) the same
interval on 2024-25 does not lie entirely below zero. Appearance Brier and log loss and
minutes MAE are reported beside the rule and do not enter it; the appearance metrics are
expected to equal the control's to rounding, since that estimator is shared.

## The decision-level reading, declared with the rule this time

The two earlier candidates had their decision-level reading added after the rule. For this
candidate it is part of the declaration: the candidate is also exported for the frozen
decision seasons 2021-22 to 2024-25 at the same commit and run through
`scripts.evaluate_phase_c_components --development-contract phase_c_component_oof_development_v2`
(147 folds, squads solved from the arm's expected points, official autosub and captain
scoring, the frozen ridge control on the same folds), and paired on the same folds against
the linear components' reading recorded beside the gradient-boosting comparison. The
promotion question is answered by both readings together: a pin is proposed only if the
points-MAE rule prefers the candidate and the paired decision-level mean against the linear
components is not negative. A positive mean whose interval crosses zero is recorded as such
and proposed on the owner's call, with the interval beside it.

## What the result can and cannot carry

- A `candidate_preferred` verdict with a non-negative decision-level reading makes the
  candidate the subject of the promotion change; it is not itself a promotion.
- A `candidate_preferred` verdict with a negative decision-level reading, or a
  `no_selection` verdict, leaves the linear control in place and the record says so.
- Neither verdict spends the locked holdout: the v2 scope reads 2025-26 as development
  data, which the manifest states on every artifact.

## Record

The comparison report (`comparison.json` and `comparison.md` under
`comparison_gradient_boosting_points/`), the decision-level reading and the manifests are
the record. The measurements index row that names this document is added when the run has
been made and links here.

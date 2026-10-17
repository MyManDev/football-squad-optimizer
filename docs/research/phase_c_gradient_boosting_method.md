# Phase C gradient-boosting candidate: declaration and comparison method

This note declares the second Phase C v2 *development* candidate and the comparison it is
measured by. It is written before the measurement and is not changed by it. It changes
nothing in the frozen Phase C v1 contract, its artifacts or its evaluation protocol, and
it does not promote anything: promotion is a separate, reviewed change that pins a model
version in `src/squadopt/live/recommendation.py`.

## Why this candidate

The live in-season path forecasts appearance with a standardized logistic regression and
minutes and points given an appearance with ridge regressions, all on the
`phase_c_component_form_window_v1` features. Private research on the same archive
(player-by-fixture rows, nine chronological test windows over 2023-24 to 2025-26, 28,117
shared player-gameweek rows) found histogram gradient-boosted trees on the same information
16% better on appearance log loss and 16% better on minutes MAE than the linear pair, with
the product-like feature subset alone still 12% better, so the gain is the learner rather
than extra features. `docs/prediction_research_agenda.md` names gradient boosting as the
rung after ridge. This declaration moves that reading into the repository's own
out-of-fold protocol, where the points metric and the decision-level comparison decide.

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
- **B, candidate:** the gradient-boosting fit, model version
  `phase_c_control_components_gbm_v1`, `ComponentModelConfig(estimator="gradient_boosting")`:
  `HistGradientBoostingClassifier` for appearance and `HistGradientBoostingRegressor`
  (squared error) for minutes and for points, each with `learning_rate=0.05`,
  `max_iter=300`, `max_leaf_nodes=31`, `min_samples_leaf=100`, `l2_regularization=1.0`,
  `early_stopping=False`, `random_state=0`. These are declared constants; no other value is
  tried and none is changed after the results are seen. No early stopping, so the same rows
  give the same model and the fit reads nothing outside its training slice. The candidate
  refuses season-age weighting, so the arm space stays at the declared pairs.

The predictions keep the control's bounds: appearance in [0, 1], minutes in
[0, 90 x fixtures], public points at or above zero, and `control_expected_points` equal to
appearance times points.

## The fixed comparison

`scripts.export_component_oof --development-scope v2 --season-weighting equal` writes the
control table `phase_c_component_oof_development_v2_equal`; adding
`--estimator gradient_boosting` writes `phase_c_component_oof_development_v2_equal_gradient_boosting`,
whose manifest records the estimator and its constants and whose per-fold records carry
`estimator`. Both must come from the same commit of a clean tree.

`scripts.compare_component_oof_development --candidate-arm gradient_boosting` reads both
through the development reader, refuses arms that are not one paired measurement (same
commit, same rows, same targets, same coverage), scores each with `evaluate_component_oof`,
and applies the acceptance rule of the v2 method unchanged: the candidate is preferred only
if (i) its 2025-26 points MAE is lower than the control's, (ii) the 90% season-aware
moving-block interval of the per-fold paired differences (control MAE minus candidate MAE)
on 2025-26 lies entirely above zero, and (iii) the same interval on 2024-25 does not lie
entirely below zero. Appearance Brier and log loss and minutes MAE are reported beside the
rule and do not enter it.

## What the result can and cannot carry

- A `candidate_preferred` verdict makes the candidate the Phase D reference for the
  development path and the subject of the promotion change; it is not itself a promotion.
- A `no_selection` verdict leaves the linear control in place; the research reading above
  then stands as a finding about appearance and minutes that the points metric did not
  confirm, and the record says so.
- Neither verdict spends the locked holdout: the v2 scope reads 2025-26 as development
  data, which the manifest states on every artifact.

## Record

The comparison report (`comparison.json` and `comparison.md` under
`comparison_gradient_boosting/`) and the two manifests are the record. The measurements
index row that names this document is added when the run has been made and links here.

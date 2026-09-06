# Phase C v2 development method: season-age weighting on the extended scope

This note records the Phase C v2 *development* path and the comparison it was built to
run. It is written before the measurement and is not changed by it. It changes nothing in
the frozen Phase C v1 contract, its artifacts, its evaluation protocol or the Phase D/E
protocols that consume them.

## What v2 is

- **Scope.** The v1 development seasons plus 2025-26
  (`COMPONENT_DEVELOPMENT_SEASONS_V2`). 2025-26 has been used elsewhere in the repository
  before, so a v2 measurement is development evidence and is never presented as an unseen
  final test. The v1 path keeps refusing 2025-26; the v2 path reads it under a separate,
  explicitly development-only contract.
- **Contract.** `scripts.export_component_oof --development-scope v2` writes
  `phase_c_component_oof_development_v2` tables with the v1 column schema and the v1
  roster contract. The manifest additionally carries `development_only: true`, the
  `weighting` block (label, model version, rule, base, normalization), a `rule_era` note,
  `locked_holdout_read` set honestly to whether 2025-26 was listed, and per-fold
  `weighting` / `training_weight_by_season` records.
- **Reader.** `read_phase_c_component_handoff(..., development_contract=DEVELOPMENT_OOF_CONTRACT_VERSION)`
  is the only way to read a v2 artifact. The default reader refuses it, and the development
  reader refuses v1 artifacts, undeclared holdout reads and artifacts without a weighting
  declaration. `evaluate_component_oof(..., development_seasons=("2025-26",))` is the
  matching explicit allowance on the scorer.

## The two arms

Both arms use the same features (`phase_c_component_form_window_v1`), the same targets,
the same three estimators and the same hyperparameters, the same folds and the same
walk-forward cutoff: every fold trains only on rows strictly before its own gameweek, and
the scaler, the estimators and the weights are all fitted inside that slice.

- **A, control:** the equal-weight fit, model version `phase_c_control_components_v1`.
- **B, candidate:** the season-age-weighted fit, model version
  `phase_c_components_season_half_life_v1`. Every training row weighs
  `0.5 ** (prediction season start year - row season start year)`: predicting 2025-26, a
  2025-26 row weighs 1, a 2024-25 row 0.5, a 2023-24 row 0.25. The weights are normalized
  to a mean of one inside each fitted subset (complete-feature rows for appearance;
  appeared rows with both conditional targets for minutes and points) and passed to the
  `StandardScaler` and the estimator of each pipeline. A training row from a season after
  the prediction season is refused as a leak. The half-life is a declared constant; no
  other value is tried and it is not changed after the results are seen.

## The scoring era

2025-26 `total_points` already include the defensive-contribution points introduced that
season, so `points_target` embeds the new scoring era for 2025-26 rows while
2021-22..2024-25 were scored without it. Nothing is added or re-thresholded, no
defensive-action column enters the panel, the features or the targets, and an absent
action count in an earlier season is absent rather than a measured zero. The manifest's
`rule_era` block records this on every v2 artifact.

## The fixed comparison

`scripts.compare_component_oof_development` reads both arms through the development
reader, refuses arms that are not one paired measurement (same commit, same rows, same
targets, same coverage), scores each with the existing `evaluate_component_oof`, and
applies the rule below.

- **Primary evaluation:** 2025-26 folds. The metric is the existing overall points MAE of
  `control_expected_points` against realized gameweek points, per fold. The paired
  statistic is control MAE minus candidate MAE per fold, summarized with the existing
  `season_aware_moving_block_interval` under `PromotionPolicy(confidence_level=0.90,
  bootstrap_resamples=5000, moving_block_length=4, deterministic_seed=0)`.
- **Previous-era control:** 2024-25 folds, reported separately with the same statistic.
  The two eras are never averaged together. Earlier seasons are descriptive only.
- **Acceptance:** the candidate is preferred only if its primary-season MAE is lower, the
  primary interval lies entirely above zero, and the previous-era interval does not lie
  entirely below zero. Otherwise there is no selection and the control remains the
  reference. No minimum effect size is imposed and none is added afterwards. Appearance
  Brier and log loss, conditional minutes and points MAE and the component-row coverage
  are reported beside the primary metric and do not enter the rule.

## What this is not

A v2 artifact is not binding evidence for Phase D, does not pin a production model, and
does not start a Phase D or E run. Measurement numbers stay with the local run and are not
published in the repository.

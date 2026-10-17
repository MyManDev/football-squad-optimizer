# Phase C gradient-boosting candidate: the out-of-fold comparison

Record of the measurement declared in [phase_c_gradient_boosting_method.md](phase_c_gradient_boosting_method.md). JSON twin: `phase_c_gradient_boosting_comparison.json`. Both arms were exported at commit `3c825721` from a clean tree under the Phase C v2 development scope (2021-22 to 2025-26, 184 walk-forward folds, 130,095 rows, 128,627 on the component route) and compared by `scripts.compare_component_oof_development --candidate-arm gradient_boosting` on 2026-10-17T09:04:04Z. 2025-26 was read as development data, as the scope declares; the locked holdout was not spent. Nothing here promotes anything: promotion is a separate reviewed change.

**Verdict under the pre-declared rule: `candidate_preferred`.** Primary season 2025-26: control points MAE 1.00578, candidate 0.98718, mean paired fold difference +0.01847 with the 90% season-aware moving-block interval [+0.01428, +0.02125] (37 paired folds). Control-era season 2024-25: 1.02523 against 1.01304, interval [+0.00675, +0.01686]. Both intervals lie above zero, so all three clauses hold.

## The three components, pooled and per season (control / candidate)

| season | appearance log loss | candidate | appearance Brier | candidate | minutes MAE | candidate | points MAE | candidate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| pooled | 0.34623 | 0.33082 | 0.10460 | 0.10066 | 16.1605 | 15.4056 | 1.07155 | 1.05504 |
| 2021-22 | 0.38735 | 0.38284 | 0.11872 | 0.11879 | 19.8276 | 19.2474 | 1.25596 | 1.24335 |
| 2022-23 | 0.35005 | 0.33668 | 0.10592 | 0.10265 | 16.8703 | 16.0998 | 1.11731 | 1.10016 |
| 2023-24 | 0.33881 | 0.31907 | 0.10213 | 0.09673 | 15.1531 | 14.2422 | 0.99740 | 0.97644 |
| 2024-25 | 0.34594 | 0.32966 | 0.10466 | 0.09996 | 15.4857 | 14.8049 | 1.02523 | 1.01304 |
| 2025-26 | 0.31886 | 0.29836 | 0.09496 | 0.08952 | 14.3393 | 13.5480 | 1.00578 | 0.98718 |

Lower is better in every column. The candidate is better on every component in every season. Pooled: appearance log loss 0.34623 to 0.33082 (4.5% lower), appearance Brier 0.10460 to 0.10066, minutes MAE 16.1605 to 15.4056 (4.7% lower), points MAE 1.0716 to 1.0550 (1.5% lower). Appearance and minutes are reported beside the rule and do not enter it.

## What this is and is not

- One paired measurement: the same rows, features, targets, routes, folds and cutoffs; only the estimator differs (linear control against histogram gradient-boosted trees with the declared constants, no early stopping, equal weighting).
- A development reading, consistent with the private research that motivated the declaration (16% better appearance log loss and minutes MAE on player-gameweek rows against a walk-forward refit of the same control, without the availability rule); the repository's own protocol finds a smaller but one-directional gain on the points metric the rule reads.
- Not a promotion. The verdict makes the candidate the Phase D reference for the development path; pinning `phase_c_control_components_gbm_v1` on the live in-season path is its own reviewed change, which this record supports.
- The availability rule, the elite-evidence path and the experimental football arm are untouched by this measurement.

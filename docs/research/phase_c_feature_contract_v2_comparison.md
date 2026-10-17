# Phase C feature contract v2: the out-of-fold comparison

Record of the measurement declared in [phase_c_feature_contract_v2_method.md](phase_c_feature_contract_v2_method.md). JSON twin: `phase_c_feature_contract_v2_comparison.json`. Both arms are the gradient-boosting pair under the v2 development scope, exported at commit `2a3ed544` from a clean tree (184 walk-forward folds, 130,095 rows, 128,627 on the component route); only the feature contract differs. Compared by `scripts.compare_component_oof_development --candidate-arm gradient_boosting_windows` on 2026-10-17T11:11:00Z. 2025-26 read as development data; nothing promoted.

**Verdict under the pre-declared rule: `candidate_preferred`.** 2025-26 points MAE 0.98718 (v1 features) against 0.96786 (v2), mean paired fold difference +0.01938, 90% season-aware moving-block interval [+0.01498, +0.02403] (37 paired folds); 2024-25 1.01304 against 1.00280, interval [+0.00792, +0.01271].

## The three components, pooled and per season (v1 features / v2 features)

| season | appearance log loss | v2 | appearance Brier | v2 | minutes MAE | v2 | points MAE | v2 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| pooled | 0.33082 | 0.31537 | 0.10066 | 0.09518 | 15.4056 | 14.3862 | 1.05504 | 1.03995 |
| 2021-22 | 0.38284 | 0.37009 | 0.11879 | 0.11372 | 19.2474 | 18.0690 | 1.24335 | 1.22831 |
| 2022-23 | 0.33668 | 0.32176 | 0.10265 | 0.09733 | 16.0998 | 15.0995 | 1.10016 | 1.08479 |
| 2023-24 | 0.31907 | 0.30104 | 0.09673 | 0.09056 | 14.2422 | 13.2508 | 0.97644 | 0.96132 |
| 2024-25 | 0.32966 | 0.31500 | 0.09996 | 0.09452 | 14.8049 | 13.8624 | 1.01304 | 1.00280 |
| 2025-26 | 0.29836 | 0.28215 | 0.08952 | 0.08422 | 13.5480 | 12.5368 | 0.98718 | 0.96786 |

Lower is better. The v2 contract is better on every component in every season: pooled appearance log loss 0.33082 to 0.31537 (4.7% lower), appearance Brier 0.10066 to 0.09518, minutes MAE 15.4056 to 14.3862 (6.6% lower), points MAE 1.05504 to 1.03995 (1.4% lower).

## What this is and is not

- One paired measurement; the rows, routes, folds, estimator and constants are identical, the windows are the only difference.
- A development reading on the points metric. The gradient-boosting estimator's own decision-level reading (`phase_c_gradient_boosting_comparison.md`) did not confirm its player-level gain, so this candidate owes the same decision-level reading before any feature-contract pin is proposed; none is proposed here.
- Serving v2 would also need captures with ten settled weeks of live history, as the declaration states.

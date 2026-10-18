# Phase C points-only gradient-boosting candidate: the out-of-fold comparison and the decision-level reading

Record of the measurement declared in [phase_c_gradient_boosting_points_method.md](phase_c_gradient_boosting_points_method.md). JSON twin: `phase_c_gradient_boosting_points_comparison.json`. Both arms were exported at commit `7118ebd9` from a clean tree under the Phase C v2 development scope (2021-22 to 2025-26, 184 walk-forward folds, 130,095 rows, 128,627 on the component route) and compared by `scripts.compare_component_oof_development --candidate-arm gradient_boosting_points` on 2026-10-17T12:58:02Z. 2025-26 was read as development data, as the scope declares; the locked holdout was not spent. Nothing here promotes anything: promotion is a separate reviewed change.

**Verdict under the pre-declared rule: `no_selection`.** Primary season 2025-26: control points MAE 1.00578, candidate 1.00787, mean paired fold difference -0.00215 with the 90% season-aware moving-block interval [-0.00411, -0.00046] (37 paired folds), which lies below zero. Control-era season 2024-25: 1.02523 against 1.02786, interval [-0.00553, +0.00137], which crosses zero.

## The three components, pooled and per season (control / candidate)

| season | appearance log loss | candidate | minutes MAE | candidate | points MAE | candidate |
| --- | --- | --- | --- | --- | --- | --- |
| pooled | 0.34623 | 0.34623 | 16.1605 | 16.1605 | 1.07155 | 1.07141 |
| 2021-22 | 0.38735 | 0.38735 | 19.8276 | 19.8276 | 1.25596 | 1.24969 |
| 2022-23 | 0.35005 | 0.35005 | 16.8703 | 16.8703 | 1.11731 | 1.11640 |
| 2023-24 | 0.33881 | 0.33881 | 15.1531 | 15.1531 | 0.99740 | 0.99789 |
| 2024-25 | 0.34594 | 0.34594 | 15.4857 | 15.4857 | 1.02523 | 1.02786 |
| 2025-26 | 0.31886 | 0.31886 | 14.3393 | 14.3393 | 1.00578 | 1.00787 |

Lower is better in every column. The appearance and minutes estimators are the control's, so those columns agree to rounding; only the conditional points estimator differs. Pooled points MAE 1.07155 to 1.07141.

## Decision-level reading (declared with the rule; a re-computation of the pre-declaration probe, added after the result)

The candidate was exported at the same commit, `7118ebd9`, for the frozen decision seasons 2021-22 to 2024-25 and run through the repository's decision comparison (`scripts.evaluate_phase_c_components --development-contract phase_c_component_oof_development_v2`, at commit `b344b9ca`): 147 folds, squads solved from the arm's expected points and scored under the official autosub and captain rules, against the frozen ridge control on the same folds. The linear components' row is the reading recorded beside the gradient-boosting comparison, exported at commit `69f18b0c` and scored at the same evaluation commit.

| arm | mean realized squad points | against the ridge control | wins / ties / losses | zero-minute starters | autosub points | solves proven optimal |
| --- | --- | --- | --- | --- | --- | --- |
| linear components | 63.4150 | +4.8912 | 83 / 8 / 56 | 83 | 230 | 106 of 147 |
| linear appearance and minutes, boosted points | 63.8844 | +5.3605 | 85 / 2 / 60 | 108 | 401 | 147 of 147 |

The last column was added after the result, descriptive, 2026-10-18, at commit `193e6895`.

Paired on the same folds, candidate minus linear: mean +0.4694 points a gameweek, median +0.0, 90% season-aware moving-block interval [-1.190, +2.218], wins / ties / losses 73 / 6 / 68; by season 2021-22 -0.757, 2022-23 +1.667, 2023-24 +2.892, 2024-25 -1.892.

**Added after the result, descriptive, 2026-10-18, computed at commit `193e6895` from the same decision artifacts and the probe's; it changes no number above.** This reading is a re-computation, not an independent confirmation. The fitted arm reproduces the recomposition probe the declaration quotes exactly: its expected points equal the probe table's on all 101,447 rows (largest absolute difference 0.0 in every expectation column), so the solver read the same inputs, and its realized squad points equal the probe's on 147 of 147 folds. Its outcome was known before the declaration was written. The interval differs from the declaration's [-1.18, +2.23] only through the bootstrap seed, which is derived from the candidate id: under the probe's id the same fold values give [-1.177, +2.231].

Also added after the result, on the same terms: the two decision tables were exported at different commits (`69f18b0c` and `7118ebd9`); their appearance and minutes columns are equal on every row (largest absolute difference 0.0). The solves are not: 41 of the linear arm's 147 component solves stopped at the 5.0 deterministic limit without a proof of optimality (FEASIBLE), against none of the candidate's. Split by the linear arm's status, candidate minus linear is +0.783 on the 106 folds where the linear solve was proven optimal (54 / 5 / 47) and -0.341 on the 41 where it was not (19 / 1 / 21), so the asymmetry does not favour the candidate.

## What this says

The rule does not prefer the candidate: with the control's appearance and minutes kept, the boosted conditional points estimator raises the 2025-26 points MAE slightly (1.00578 to 1.00787, interval below zero, so that reading is separated from zero against the candidate) and leaves 2024-25 across zero. Read with the earlier records, this suggests that the boosted pair's points-MAE gain came from its appearance estimator rather than its points estimator. One possible mechanism, not measured here, is that a sharper appearance probability pulls uncertain players toward the zero that most realized points are, which the error metric rewards. The decision-level reading goes the other way: this arm's squads score the most realized points of any component arm measured (+5.36 a gameweek against the ridge control, +0.47 against the linear components), with the interval across zero, 73 wins to 68 losses, two seasons up and two down. As the paragraph added after the result shows (2026-10-18, at commit `193e6895`), that reading re-computes the recomposition probe the declaration quotes, so it repeats that probe rather than confirming it. The two readings disagree: the points-MAE reading is separated from zero against the candidate on 2025-26 and crosses zero on 2024-25, and the decision-level reading is not separated from zero. The declaration's pin condition (rule preferred and a non-negative decision mean) is not met. The linear control stays in place; the record stands as the finding that the points-MAE rule and realized squad points can move in opposite directions on the same arm.

- One paired measurement at the player level: the same rows, features, targets, routes, folds and cutoffs; only the conditional points estimator differs. At the decision level, as added after the result (2026-10-18, at commit `193e6895`), the appearance and minutes columns are equal too and only the conditional points differ, but the linear arm's solves were proven optimal on 106 of 147 folds and the candidate's on all 147.
- The availability rule, the elite-evidence path and the experimental football arm are untouched by this measurement.

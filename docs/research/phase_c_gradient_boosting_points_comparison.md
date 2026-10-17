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

## Decision-level reading (declared with the rule)

The candidate was exported at the same commit for the frozen decision seasons 2021-22 to 2024-25 and run through the repository's decision comparison (`scripts.evaluate_phase_c_components --development-contract phase_c_component_oof_development_v2`): 147 folds, squads solved from the arm's expected points and scored under the official autosub and captain rules, against the frozen ridge control on the same folds. The linear components' row is the reading recorded beside the gradient-boosting comparison.

| arm | mean realized squad points | against the ridge control | wins / ties / losses | zero-minute starters | autosub points |
| --- | --- | --- | --- | --- | --- |
| linear components | 63.4150 | +4.8912 | 83 / 8 / 56 | 83 | 230 |
| linear appearance and minutes, boosted points | 63.8844 | +5.3605 | 85 / 2 / 60 | 108 | 401 |

Paired on the same folds, candidate minus linear: mean +0.4694 points a gameweek, median +0.0, 90% season-aware moving-block interval [-1.190, +2.218], wins / ties / losses 73 / 6 / 68; by season 2021-22 -0.757, 2022-23 +1.667, 2023-24 +2.892, 2024-25 -1.892.

## What this says

The rule does not prefer the candidate: with the control's appearance and minutes kept, the
boosted conditional points estimator raises the 2025-26 points MAE slightly (1.00578 to
1.00787, interval below zero) and leaves 2024-25 across zero. Read with the earlier records,
this places the boosted pair's points-MAE gain in its appearance estimator, not in its points
estimator: a sharper appearance probability shrinks uncertain players toward the zero that
most realized points are, which the error metric rewards and the solver does not. The
decision-level reading goes the other way, as the recomposition probe said it would: this
arm's squads score the most realized points of any component arm measured (+5.36 a gameweek
against the ridge control, +0.47 against the linear components), with the interval across
zero, 73 wins to 68 losses, two seasons up and two down. The two readings disagree, neither
is separated from zero, and the declaration's pin condition (rule preferred and a non-negative
decision mean) is not met. The linear control stays in place; the record stands as the
finding that the points-MAE rule and realized squad points can move in opposite directions
on the same arm.

- One paired measurement at each level: the same rows, features, targets, routes, folds and cutoffs; only the conditional points estimator differs.
- The availability rule, the elite-evidence path and the experimental football arm are untouched by this measurement.

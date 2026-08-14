# Production gate judgement

A **development gate verdict**, not an operational promotion. Clearing these gates makes a candidate eligible for the locked holdout protocol; it does not by itself put anything into production.

Verdict: **no_promotion_control_retained**

## Fold set

- Seasons: `2021-22, 2022-23, 2023-24, 2024-25`
- Folds: `147`
- Feasible folds: baseline `147`, production `147`, ridge `147`
- The 2025-26 holdout is untouched.

## Mean realized squad points

| Candidate | Mean realized |
| --- | ---: |
| baseline | 53.7755 |
| production | 57.4150 |
| ridge | 57.3129 |

## Paired comparisons

| Candidate | Reference | Mean | 90% interval | Stdev | W/T/L |
| --- | --- | ---: | --- | ---: | --- |
| production | baseline | +3.6395 | `[+1.7548, +5.8095]` | 14.8056 | 73/22/52 |
| production | ridge | +0.1020 | `[-2.1364, +2.2381]` | 16.5392 | 69/5/73 |
| ridge | baseline | +3.5374 | `[+1.9728, +5.3816]` | 12.8832 | 81/10/56 |

## Prediction metrics

| Candidate | Observations | MAE | RMSE | Bias |
| --- | ---: | ---: | ---: | ---: |
| baseline | 101,447 | 1.1237 | 2.2335 | +0.0055 |
| production | 101,447 | 1.1230 | 2.2054 | +0.0500 |
| ridge | 101,447 | 1.1300 | 2.0991 | +0.0080 |

### Production, by position

Reported per position rather than pooled, because pooling is what hides a systematic skew.

| Position | Observations | MAE | RMSE | Bias |
| --- | ---: | ---: | ---: | ---: |
| GK | 11,145 | 0.7726 | 1.7631 | +0.0297 |
| DEF | 34,039 | 1.1963 | 2.2368 | +0.0495 |
| MID | 43,826 | 1.1185 | 2.2068 | +0.0488 |
| FWD | 12,437 | 1.2520 | 2.4564 | +0.0738 |

## Pre-registered gates

| Condition | Required | Measured | Verdict |
| --- | --- | ---: | --- |
| `baseline_mean_improvement` | >= +0.5000 | +3.6395 | pass |
| `baseline_lower_bound` | >= +0.0000 | +1.7548 | pass |
| `ridge_mean_difference` | >= +0.0000 | +0.1020 | pass |
| `ridge_lower_bound` | >= -0.5000 | -2.1364 | **fail** |
| `prediction_metric_improved_against_ridge` | MAE or RMSE improves | -0.0063 | pass |
| `other_prediction_metric_tolerance` | <= +0.0500 relative degradation | +0.0507 | **fail** |
| `every_fold_feasible` | = 147 folds | +147.0000 | pass |

## Solver truncation

**ridge did not solve every fold to optimality.** Those folds returned the best squad found before the time limit, not the best squad for that candidate's own projection, so its realized points are depressed by the search rather than by its prediction. The run is also not reproducible for that candidate: a wall-clock limit makes the answer depend on how much work the machine completed.

| Candidate | Solver outcomes |
| --- | --- |
| baseline | OPTIMAL 147 |
| production | OPTIMAL 147 |
| ridge | FEASIBLE 33, OPTIMAL 114 |

## Environment

Recorded because a numerical solve is sensitive to the libraries underneath it. The Ridge reference is measured in this run rather than read from an earlier artifact, since comparing against a figure recorded on another machine would measure the machines as much as the models.

- numpy: `2.4.6`
- ortools: `9.15.6755`
- pandas: `3.0.5`
- platform: `Windows-10-10.0.26200-SP0`
- processor: `Intel64 Family 6 Model 141 Stepping 1, GenuineIntel`
- python: `3.11.0`
- scikit_learn: `1.9.0`

# Production gate judgement

A **development gate verdict**, not an operational promotion. Clearing these gates makes a candidate eligible for the locked holdout protocol; it does not by itself put anything into production.

Verdict: **no_promotion_control_retained**

## Fold set

- Seasons: `2021-22, 2022-23, 2023-24, 2024-25`
- Folds: `147`
- Feasible folds: baseline `147`, production `147`, ridge `147`
- The 2025-26 holdout is untouched.
- Solver stopping rule: deterministic work budget `0.5` with wall-clock safety cap `120.0s`.

## Mean realized squad points

| Candidate | Mean realized |
| --- | ---: |
| baseline | 53.2585 |
| production | 57.7483 |
| ridge | 57.1020 |

## Paired comparisons

| Candidate | Reference | Mean | 90% interval | Stdev | W/T/L |
| --- | --- | ---: | --- | ---: | --- |
| production | baseline | +4.4898 | `[+2.5643, +6.6939]` | 15.4833 | 81/20/46 |
| production | ridge | +0.6463 | `[-1.6194, +2.9524]` | 16.9592 | 71/5/71 |
| ridge | baseline | +3.8435 | `[+2.2313, +5.6735]` | 13.0928 | 83/7/57 |

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
| `baseline_mean_improvement` | >= +0.5000 | +4.4898 | pass |
| `baseline_lower_bound` | >= +0.0000 | +2.5643 | pass |
| `ridge_mean_difference` | >= +0.0000 | +0.6463 | pass |
| `ridge_lower_bound` | >= -0.5000 | -1.6194 | **fail** |
| `prediction_metric_improved_against_ridge` | MAE or RMSE improves | -0.0063 | pass |
| `other_prediction_metric_tolerance` | <= +0.0500 relative degradation | +0.0507 | **fail** |
| `every_fold_feasible` | = 147 folds | +147.0000 | pass |

## Solver truncation

**ridge did not solve every fold to optimality.** Those folds returned the incumbent selected after the same deterministic amount of CP-SAT work. Their realized points therefore contain search noise of unknown direction, not a known downward bias. The wall-clock limit is only a safety cap; the run is rejected if that cap binds first.

| Candidate | Solver outcomes |
| --- | --- |
| baseline | OPTIMAL 147 |
| production | OPTIMAL 147 |
| ridge | FEASIBLE 118, OPTIMAL 29 |

## Environment

Recorded because a numerical solve is sensitive to the libraries underneath it. The Ridge reference is measured in this run rather than read from an earlier artifact, since comparing against a figure recorded on another machine would measure the machines as much as the models.

- numpy: `2.5.2`
- ortools: `9.15.6755`
- pandas: `3.0.5`
- platform: `Windows-11-10.0.26200-SP0`
- processor: `Intel64 Family 6 Model 183 Stepping 1, GenuineIntel`
- python: `3.13.5`
- scikit_learn: `1.9.0`

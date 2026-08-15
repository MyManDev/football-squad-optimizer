# Control uncertainty calibration (development-internal)

- Calibration seasons: 2021-22, 2022-23, 2023-24 (110 folds)
- Evaluation season: 2024-25 (37 folds, frozen calibrations, no refit)
- Confidence level: 0.9
- Baseline form window: 5
- The 2025-26 locked holdout was **not** read.

| Calibration | Population | Observations | Coverage | Mean width | MAE | RMSE |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Position-level | All | 26303 | 0.9096 | 6.8514 | 1.0610 | 2.1172 |
| Position-level | DEF | 8821 | 0.9206 | 7.6000 | 1.0599 | 2.0226 |
| Position-level | FWD | 2913 | 0.8881 | 7.6000 | 1.2349 | 2.4416 |
| Position-level | GK | 2761 | 0.9095 | 5.6000 | 0.7803 | 1.7707 |
| Position-level | MID | 11808 | 0.9066 | 6.4000 | 1.0846 | 2.1738 |
| Player-adaptive | All | 26303 | 0.8968 | 6.0641 | 1.0610 | 2.1172 |
| Player-adaptive | DEF | 8821 | 0.9052 | 6.6878 | 1.0599 | 2.0226 |
| Player-adaptive | FWD | 2913 | 0.8692 | 6.8140 | 1.2349 | 2.4416 |
| Player-adaptive | GK | 2761 | 0.9037 | 4.5395 | 0.7803 | 1.7707 |
| Player-adaptive | MID | 11808 | 0.8957 | 5.7696 | 1.0846 | 2.1738 |

The comparison to read: at the same confidence level, does the player-adaptive
calibration hold coverage while narrowing the mean interval width?

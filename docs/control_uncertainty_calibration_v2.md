# Control uncertainty calibration (development-internal)

- Calibration seasons: 2021-22, 2022-23, 2023-24 (110 folds)
- Evaluation season: 2024-25 (37 folds, frozen calibrations, no refit)
- Confidence level: 0.9
- Baseline form window: 5
- Grouping: position_fixture_group (`projection_uncertainty_v2`)
- The 2025-26 locked holdout was **not** read.

| Calibration | Population | Observations | Coverage | Mean width | MAE | RMSE |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Position-level | All | 26303 | 0.9100 | 6.8929 | 1.0610 | 2.1172 |
| Position-level | DEF | 8821 | 0.9222 | 7.6498 | 1.0599 | 2.0226 |
| Position-level | FWD | 2913 | 0.8884 | 7.6420 | 1.2349 | 2.4416 |
| Position-level | GK | 2761 | 0.9095 | 5.6243 | 0.7803 | 1.7707 |
| Position-level | MID | 11808 | 0.9064 | 6.4394 | 1.0846 | 2.1738 |
| Player-adaptive | All | 26303 | 0.8968 | 6.0641 | 1.0610 | 2.1172 |
| Player-adaptive | DEF | 8821 | 0.9052 | 6.6878 | 1.0599 | 2.0226 |
| Player-adaptive | FWD | 2913 | 0.8692 | 6.8140 | 1.2349 | 2.4416 |
| Player-adaptive | GK | 2761 | 0.9037 | 4.5395 | 0.7803 | 1.7707 |
| Player-adaptive | MID | 11808 | 0.8957 | 5.7696 | 1.0846 | 2.1738 |

Fixture-group populations (position-level calibration, held-out season):

| Population | Observations | Coverage | Mean width | MAE |
| --- | ---: | ---: | ---: | ---: |
| double_plus | 364 | 0.8626 | 9.83 | 1.99 |
| single | 25939 | 0.9107 | 6.85 | 1.05 |
| DEF/double_plus | 122 | 0.9180 | 11.20 | 1.84 |
| DEF/single | 8699 | 0.9223 | 7.60 | 1.05 |
| FWD/double_plus | 34 | 0.8235 | 11.20 | 2.26 |
| FWD/single | 2879 | 0.8892 | 7.60 | 1.22 |
| GK/double_plus | 42 | 0.8333 | 7.20 | 1.29 |
| GK/single | 2719 | 0.9106 | 5.60 | 0.77 |
| MID/double_plus | 166 | 0.8373 | 9.20 | 2.23 |
| MID/single | 11642 | 0.9074 | 6.40 | 1.07 |

The comparison to read: at the same confidence level, does the player-adaptive
calibration hold coverage while narrowing the mean interval width?

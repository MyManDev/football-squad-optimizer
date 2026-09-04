# Residual signal scan

- Contract: `residual_signal_scan_v1`; lag window 6 gameweeks
- Seasons: 2021-22, 2022-23, 2023-24, 2024-25; residual rows 101447
- Every covariate is strictly lagged or published before the deadline. Residual spread = max minus min mean residual across bins; surviving ratio = residual spread over raw realized spread (above one: the model widened the effect).

## `xgi_per_90_last` — expected goal involvement per 90 over the previous window (xG data from 2022-23)

- Rows 44511; seasons 2022-23, 2023-24, 2024-25
- Residual spread **+0.3176**; realized spread +0.9700; surviving ratio 0.33; monotone residual: no

| Bin | Rows | Mean covariate | Realized | Residual |
| --- | ---: | ---: | ---: | ---: |
| Q1 | 11132 | 0.000 | 1.6840 | +0.0157 |
| Q2 | 11124 | 0.046 | 1.6637 | +0.0765 |
| Q3 | 11128 | 0.175 | 2.0785 | -0.0179 |
| Q4 | 11127 | 0.678 | 2.6337 | -0.2411 |

## `luck_last` — returns minus expected goal involvement over the previous window; positive = ran hot

- Rows 78191; seasons 2022-23, 2023-24, 2024-25
- Residual spread **+1.0669**; realized spread +2.3417; surviving ratio 0.46; monotone residual: yes

| Bin | Rows | Mean covariate | Realized | Residual |
| --- | ---: | ---: | ---: | ---: |
| Q1 | 19682 | -0.378 | 1.8744 | +0.3278 |
| Q2 | 44591 | -0.000 | 0.3791 | +0.0887 |
| Q3 | 13918 | 1.122 | 2.7207 | -0.7391 |

## `ownership_prev` — ownership count at the previous gameweek

- Rows 100684; seasons 2021-22, 2022-23, 2023-24, 2024-25
- Residual spread **+0.2468**; realized spread +2.4311; surviving ratio 0.10; monotone residual: no

| Bin | Rows | Mean covariate | Realized | Residual |
| --- | ---: | ---: | ---: | ---: |
| Q1 | 25172 | 1571.612 | 0.2396 | +0.0574 |
| Q2 | 25170 | 9846.069 | 0.6967 | +0.0738 |
| Q3 | 25171 | 51961.143 | 1.2447 | +0.0495 |
| Q4 | 25171 | 793618.658 | 2.6707 | -0.1731 |

## `source_xp` — the source's own published point expectation for the gameweek

- Rows 101447; seasons 2021-22, 2022-23, 2023-24, 2024-25
- Residual spread **+0.6771**; realized spread +3.6465; surviving ratio 0.19; monotone residual: no

| Bin | Rows | Mean covariate | Realized | Residual |
| --- | ---: | ---: | ---: | ---: |
| Q1 | 50246 | -0.113 | 0.1375 | -0.1544 |
| Q2 | 2440 | 0.182 | 0.4689 | -0.1285 |
| Q3 | 23634 | 0.912 | 0.8161 | -0.1949 |
| Q4 | 25127 | 3.874 | 3.7840 | +0.4822 |

## `recently_moved` — changed club within the previous window (in-season)

- Rows 101447; seasons 2021-22, 2022-23, 2023-24, 2024-25
- Residual spread **+0.6253**; realized spread +0.2916; surviving ratio 2.14; monotone residual: yes

| Bin | Rows | Mean covariate | Realized | Residual |
| --- | ---: | ---: | ---: | ---: |
| recently_moved | 594 | 1.000 | 1.4966 | +0.6161 |
| unchanged | 100853 | 0.000 | 1.2050 | -0.0092 |

Measurement only: no feature, contract, or model changed; the locked holdout was
not read.

# Projection shrinkage grid

- Contract: `projection_shrinkage_grid_v1`; rule `position_mean_shrinkage_v1`
- 147 development folds; bench_weight=0.0

Does the optimizer pick better squads from shrunken projections?

| form_window | shrinkage | Mean realized | Delta vs unshrunk |
| ---: | ---: | ---: | ---: |
| 5 | 0.00 | 54.2109 | +0.0000 |
| 6 | 0.00 | 54.7959 | +0.0000 |
| 10 | 0.00 | 56.5034 | +0.0000 |
| 5 | 0.10 | 54.2449 | +0.0340 |
| 6 | 0.10 | 54.8367 | +0.0408 |
| 10 | 0.10 | 56.8027 | +0.2993 |
| 5 | 0.20 | 54.2381 | +0.0272 |
| 6 | 0.20 | 54.8231 | +0.0272 |
| 10 | 0.20 | 56.7347 | +0.2313 |
| 5 | 0.30 | 54.2381 | +0.0272 |
| 6 | 0.30 | 54.7619 | -0.0340 |
| 10 | 0.30 | 56.7279 | +0.2245 |
| 5 | 0.50 | 54.2721 | +0.0612 |
| 6 | 0.50 | 54.8844 | +0.0884 |
| 10 | 0.50 | 56.8844 | +0.3810 |

Recommendation-only measurement: no promotion, no locked-holdout access.

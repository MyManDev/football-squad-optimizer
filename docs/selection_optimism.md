# Selection optimism profile

- Contract: `selection_optimism_profile_v1`
- Folds: 147; anchor form_window=6, bench_weight=0.0

| Population | Mean residual (realized minus projected) |
| --- | ---: |
| Full roster | -0.004 |
| Selected starters | -2.956 |
| Captains | -3.863 |

**Selection gap: -2.951 points per starter** (x 11 starters + doubled captain approximates the squad-level bias). Projected XI mean 91.17 vs realized 54.80.

## By projection rank (within each fold's roster)

| Rank bucket | Mean residual |
| --- | ---: |
| top_05 | -3.532 |
| rank_06_15 | -2.464 |
| rank_16_plus | +0.058 |

## Selected starters by position

| Position | Mean residual |
| --- | ---: |
| DEF | -3.053 |
| FWD | -2.726 |
| GK | -2.638 |
| MID | -3.061 |

Measurement only. The profile tells a correction where to act; it does not
apply one.

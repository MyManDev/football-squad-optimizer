# A Gaussian process against four constants: pricing the rest of the season

- Contract `terminal_value_gp_v1`; 2860 state rows from 80 recorded chains across 6 chip-mode variants; leave-one-season-out over 2021-22, 2022-23, 2023-24, 2024-25.
- Target: net points from the next week to the season's end. Baseline: remaining weeks x the training seasons' mean weekly net, plus the holding values of chips still in hand (bboost 20, 3xc 18, wildcard 12, freehit 20). Gate declared in `terminal_value_prereg.md` before anything was fitted.
- Fitted kernel (last fold): `0.729**2 * RBF(length_scale=[0.441, 1.2, 1.38, 30.1, 9.92, 10.2, 20.1, 12.8]) + WhiteKernel(noise_level=0.0128)`.

| Season | Rows | GP MAE | Baseline MAE | Improvement |
| --- | ---: | ---: | ---: | ---: |
| 2021-22 | 720 | 96.00 | 79.97 | -16.03 |
| 2022-23 | 700 | 93.19 | 58.07 | -35.12 |
| 2023-24 | 720 | 117.20 | 91.59 | -25.60 |
| 2024-25 | 720 | 119.04 | 106.68 | -12.36 |
| **pooled** | 2860 | **106.45** | **84.26** | **-22.19** |

## By phase of the season (reported, not gated)

| Band | Rows | GP MAE | Baseline MAE |
| --- | ---: | ---: | ---: |
| early_25_plus_weeks_left | 940 | 113.90 | 104.68 |
| mid_10_to_24_weeks_left | 1200 | 104.27 | 82.03 |
| late_under_10_weeks_left | 720 | 100.35 | 61.32 |

## Verdict

- Pooled improvement: -22.19 MAE; better in 0 of 4 seasons.
**The gate fails**: the holding-value constants are not improved upon by this state representation. The constants stand, and the negative is recorded.


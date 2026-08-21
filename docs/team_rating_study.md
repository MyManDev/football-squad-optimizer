# A team rating from goals, against the rating the platform ships

- Contract `team_rating_study_v1`; fitted on 2020-21, 2021-22, 2022-23, 2023-24, 2024-25, judged walk-forward on 2022-23, 2023-24, 2024-25 from gameweek 6.
- Dixon-Coles refitted at every judged gameweek on matches that kicked off before it (98 fits). The half life and ridge are chosen per judged season on the seasons before it: half lives {'2022-23': 500.0, '2023-24': 180.0, '2024-25': 180.0}, ridges {'2022-23': 2.0, '2023-24': 5.0, '2024-25': 5.0}.
- 2000 bootstrap resamples, seed 0.
- Measurement only. The locked 2025-26 holdout is refused by the configuration, no model or contract changed, and the verdict was computed by `rating_gate_verdict`.

## Season by season

| Season | Fixtures | Rating log-lik | Baseline log-lik | Rating Brier | Uncalibrated | Published Brier | Refits |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2022-23 | 330 | -3.0537 | -3.1250 | 0.1953 | 0.1949 | 0.1947 | 32 |
| 2023-24 | 331 | -3.1161 | -3.2467 | 0.1574 | 0.1579 | 0.1687 | 33 |
| 2024-25 | 330 | -2.9974 | -3.1014 | 0.1726 | 0.1727 | 0.1723 | 33 |

| Season | Attacking (rating / published) | Defensive (rating / published) | Clean sheets predicted / realized |
| --- | --- | --- | --- |
| 2022-23 | +0.0750 / +0.0155 | +0.0592 / +0.0369 | 0.264 / 0.276 |
| 2023-24 | +0.0599 / +0.0178 | +0.0903 / +0.0639 | 0.247 / 0.208 |
| 2024-25 | +0.0545 / +0.0304 | +0.0527 / +0.0410 | 0.231 / 0.236 |

## Pooled

- Log-likelihood per fixture against the constant-rate baseline: **+0.1020** [+0.0756, +0.1323].
- Clean-sheet Brier against a logistic on the published rating: **+0.0035** [+0.0006, +0.0062] (positive means the rating is better calibrated).
- Ordering player points, attacking side: rating +0.0631 against published +0.0213; defensive side: +0.0674 against +0.0473.

## Clean-sheet reliability

| Bin | Rows | Predicted | Published | Realized |
| --- | ---: | ---: | ---: | ---: |
| 0.0-0.1 | 179 | 0.071 | 0.161 | 0.084 |
| 0.1-0.2 | 565 | 0.154 | 0.223 | 0.172 |
| 0.2-0.3 | 623 | 0.249 | 0.288 | 0.244 |
| 0.3-0.4 | 394 | 0.343 | 0.336 | 0.325 |
| 0.4-0.5 | 181 | 0.438 | 0.369 | 0.392 |
| 0.5-0.6 | 40 | 0.534 | 0.389 | 0.325 |

## Verdict

The gate: better than a constant-rate baseline at predicting goals in every judged season with the pooled interval clear of zero; better calibrated clean sheets than a logistic on the published rating, pooled and in all but at most one season; and an ordering of player points at least as strong as the published rating on both sides of the ball.

- Goals: passes (sign consistent: True; interval clears zero: True).
- Clean sheets: fails (1 of 3 seasons better).
- Players: passes.

**The rating does not clear its gate.**


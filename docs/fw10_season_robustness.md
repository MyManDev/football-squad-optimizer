# fw10 season robustness

- Contract: `fw10_season_robustness_v1`
- Challenger `fw10-bw0` vs control `fw05-bw0p1`, each season evaluated in isolation on identical folds

| Season | Folds | Challenger | Control | Delta |
| --- | ---: | ---: | ---: | ---: |
| 2021-22 | 37 | 56.1081 | 54.5405 | +1.5676 |
| 2022-23 | 36 | 58.4722 | 55.1389 | +3.3333 |
| 2023-24 | 37 | 54.4595 | 51.6486 | +2.8108 |
| 2024-25 | 37 | 57.0270 | 53.8108 | +3.2162 |

**4/4 seasons positive; mean +2.73, worst season +1.57.**

Evidence for the deferred holdout decision only; nothing is promoted and
the locked holdout was not read.

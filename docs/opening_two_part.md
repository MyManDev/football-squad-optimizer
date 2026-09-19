# The two-part opening projection

Contract `opening_two_part_v1`. Protocol: `docs/opening_two_part_prereg.md`, committed 2026-08-26 before anything was fitted. **Verdict: passes.**

The shape: expected points = P(plays | ownership, price, position) times E[points | plays, price, position]. Seasons read 2020-21, 2021-22, 2022-23, 2023-24, 2024-25, judged 2022-23, 2023-24, 2024-25. Locked holdout accessed: False.

## The gate, as the protocol fixed it

| Clause | Reading | Passes |
| --- | --- | --- |
| 1 accuracy | pooled improvement +0.4985, 90% interval [+0.4641, +0.5331], improves every season True | yes |
| 2 ordering | worst season shortfall -0.0022, pooled -0.0203, tolerance 0.010 | yes |
| 3 decision | mean +3.667 points, 0 losing season(s) | yes |

## Per judged season

| Season | Rows | Control MAE | Candidate MAE | Improvement | Control rank | Candidate rank | Shortfall |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2022-23 | 202 | 1.3910 | 0.9881 | +0.4029 | 0.5152 | 0.5634 | -0.0482 |
| 2023-24 | 253 | 1.2912 | 0.7549 | +0.5363 | 0.4713 | 0.4736 | -0.0022 |
| 2024-25 | 201 | 1.2271 | 0.6801 | +0.5471 | 0.5110 | 0.5214 | -0.0104 |

## Reported, not gated

Calibration of part one, predicted against realized play rate by decile:

| Season | Decile | Rows | Predicted | Realized |
| --- | ---: | ---: | ---: | ---: |
| 2022-23 | 1 | 21 | 0.1174 | 0.0000 |
| 2022-23 | 2 | 21 | 0.1902 | 0.2857 |
| 2022-23 | 3 | 20 | 0.2608 | 0.1000 |
| 2022-23 | 4 | 20 | 0.2616 | 0.0500 |
| 2022-23 | 5 | 20 | 0.2633 | 0.2500 |
| 2022-23 | 6 | 20 | 0.2907 | 0.4000 |
| 2022-23 | 7 | 20 | 0.3653 | 0.5000 |
| 2022-23 | 8 | 20 | 0.3669 | 0.4000 |
| 2022-23 | 9 | 20 | 0.4254 | 0.7500 |
| 2022-23 | 10 | 20 | 0.6223 | 0.8500 |
| 2023-24 | 1 | 26 | 0.0915 | 0.0000 |
| 2023-24 | 2 | 26 | 0.1148 | 0.0385 |
| 2023-24 | 3 | 26 | 0.1815 | 0.2692 |
| 2023-24 | 4 | 25 | 0.2200 | 0.0800 |
| 2023-24 | 5 | 25 | 0.2347 | 0.1200 |
| 2023-24 | 6 | 25 | 0.2362 | 0.0800 |
| 2023-24 | 7 | 25 | 0.2377 | 0.3200 |
| 2023-24 | 8 | 25 | 0.3236 | 0.6000 |
| 2023-24 | 9 | 25 | 0.3866 | 0.4000 |
| 2023-24 | 10 | 25 | 0.5786 | 0.8800 |
| 2024-25 | 1 | 21 | 0.0893 | 0.0000 |
| 2024-25 | 2 | 20 | 0.1645 | 0.1500 |
| 2024-25 | 3 | 20 | 0.2104 | 0.0500 |
| 2024-25 | 4 | 20 | 0.2122 | 0.1000 |
| 2024-25 | 5 | 20 | 0.2184 | 0.1500 |
| 2024-25 | 6 | 20 | 0.2275 | 0.1000 |
| 2024-25 | 7 | 20 | 0.2711 | 0.3500 |
| 2024-25 | 8 | 20 | 0.3869 | 0.5500 |
| 2024-25 | 9 | 20 | 0.4498 | 0.6000 |
| 2024-25 | 10 | 20 | 0.7231 | 0.7500 |

Both arms on the newcomers who actually took the field. This is what says whether the headline improvement is real or is bought from the players who never appear:

| Season | Played rows | Control bias | Candidate bias | Control MAE | Candidate MAE | Control rank | Candidate rank | No published ownership |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2022-23 | 72 | +0.9030 | +1.2519 | 1.4970 | 1.5618 | 0.1687 | 0.0863 | 14 |
| 2023-24 | 70 | +0.3893 | +0.8428 | 1.2258 | 1.3619 | 0.2196 | 0.0966 | 14 |
| 2024-25 | 56 | +0.2101 | +0.6406 | 0.9668 | 1.0864 | 0.2933 | 0.2817 | 4 |

## The decision clause's solves

| Season | Control | Candidate | Difference | Changed starters |
| --- | --- | --- | ---: | ---: |
| 2022-23 | OPTIMAL | OPTIMAL | +11 | 1 |
| 2023-24 | FEASIBLE | FEASIBLE | +0 | 0 |
| 2024-25 | FEASIBLE | FEASIBLE | +0 | 0 |

## What this measurement cannot conclude

Part one's target is minutes above zero at the opening gameweek, which is a play label and not an availability label: the archive carries no status, news or chance-of-playing column at gameweek one, so no availability label exists to fit. Nothing here says the factor learned who was available, only who took the field.


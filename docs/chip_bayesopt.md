# Bayesian search over chip holding values and planning hit cost (season chain)

- Contract `chip_bayesopt_v1` on `deterministic_policy_bo_v1`; seasons 2021-22, 2022-23, 2023-24, 2024-25; chip mode hybrid; budget 20 (8 initial); 34 min.
- Objective: mean season net minus 1 x season standard deviation.

| Iteration | Phase | bboost | 3xc | wildcard | freehit | hit cost | Mean net | Spread | Robust |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | initial_design | 25 | 30 | 16 | 15 | 8 | 2022 | 86 | 1935.1 |
| 1 | initial_design | 0 | 0 | 0 | 0 | 4 | 2028 | 133 | 1894.7 |
| 2 | initial_design | 15 | 0 | 24 | 20 | 4 | 1985 | 131 | 1854.4 |
| 3 | initial_design | 0 | 5 | 24 | 0 | 8 | 2030 | 52 | 1977.9 |
| 4 | initial_design | 0 | 30 | 0 | 20 | 4 | 2018 | 136 | 1882.2 |
| 5 | initial_design | 0 | 0 | 0 | 20 | 8 | 2007 | 95 | 1911.8 |
| 6 | initial_design | 30 | 30 | 0 | 0 | 4 | 1980 | 133 | 1846.9 |
| 7 | initial_design | 30 | 0 | 0 | 0 | 8 | 1972 | 81 | 1891.4 |
| 8 | expected_improvement | 0 | 20 | 24 | 0 | 8 | 2034 | 50 | 1984.3 |
| 9 | expected_improvement | 0 | 15 | 24 | 5 | 8 | 2024 | 117 | 1906.3 |
| 10 | expected_improvement | 5 | 30 | 24 | 0 | 8 | 2026 | 50 | 1975.7 |
| 11 | expected_improvement | 0 | 25 | 16 | 0 | 8 | 2009 | 63 | 1946.1 |
| 12 | expected_improvement | 15 | 20 | 24 | 0 | 8 | 2034 | 56 | 1977.4 |
| 13 | expected_improvement | 30 | 30 | 24 | 0 | 8 | 2022 | 54 | 1967.1 |
| 14 | expected_improvement | 15 | 0 | 24 | 0 | 8 | 2029 | 59 | 1969.3 |
| 15 | expected_improvement | 0 | 20 | 24 | 0 | 7 | 2054 | 65 | 1988.6 |
| 16 | expected_improvement | 0 | 30 | 24 | 0 | 5 | 2002 | 99 | 1903.3 |
| 17 | expected_improvement | 5 | 15 | 24 | 0 | 7 | 2054 | 70 | 1983.9 |
| 18 | expected_improvement | 0 | 0 | 24 | 0 | 6 | 2023 | 75 | 1948.4 |
| 19 | expected_improvement | 0 | 15 | 24 | 0 | 7 | 2050 | 77 | 1972.9 |

Recommended candidate: `bboost_hold=0-freehit_hold=0-planning_hit_cost=7-threexc_hold=20-wildcard_hold=24` — a candidate for the next season chain and the gates, not a promotion. Measurement only; the 2025-26 holdout was not read.

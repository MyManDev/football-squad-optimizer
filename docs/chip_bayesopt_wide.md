# Bayesian search over chip holding values and planning hit cost (season chain)

- Contract `chip_bayesopt_v1` on `deterministic_policy_bo_v1`; seasons 2021-22, 2022-23, 2023-24, 2024-25; chip mode hybrid; budget 20 (8 initial); 32 min.
- Objective: mean season net minus 1 x season standard deviation.

| Iteration | Phase | bboost | 3xc | wildcard | freehit | hit cost | Mean net | Spread | Robust |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | initial_design | 25 | 30 | 28 | 10 | 6 | 2000 | 87 | 1912.2 |
| 1 | initial_design | 0 | 0 | 0 | 0 | 4 | 2028 | 133 | 1894.7 |
| 2 | initial_design | 0 | 0 | 40 | 20 | 8 | 2021 | 70 | 1951.2 |
| 3 | initial_design | 30 | 0 | 0 | 0 | 8 | 1972 | 81 | 1891.4 |
| 4 | initial_design | 30 | 0 | 0 | 20 | 4 | 1999 | 144 | 1855.0 |
| 5 | initial_design | 0 | 25 | 0 | 0 | 8 | 2001 | 102 | 1899.2 |
| 6 | initial_design | 0 | 25 | 0 | 20 | 4 | 2024 | 123 | 1900.2 |
| 7 | initial_design | 30 | 0 | 40 | 0 | 4 | 1948 | 112 | 1836.6 |
| 8 | expected_improvement | 0 | 15 | 40 | 20 | 8 | 2029 | 75 | 1953.8 |
| 9 | expected_improvement | 0 | 10 | 28 | 20 | 8 | 2071 | 98 | 1973.1 |
| 10 | expected_improvement | 0 | 5 | 16 | 20 | 8 | 2062 | 95 | 1966.8 |
| 11 | expected_improvement | 0 | 15 | 20 | 20 | 8 | 2040 | 96 | 1944.9 |
| 12 | expected_improvement | 0 | 5 | 28 | 20 | 8 | 2071 | 98 | 1973.1 |
| 13 | expected_improvement | 0 | 5 | 28 | 15 | 8 | 2047 | 88 | 1959.2 |
| 14 | expected_improvement | 10 | 5 | 28 | 20 | 8 | 2072 | 98 | 1974.6 |
| 15 | expected_improvement | 5 | 5 | 28 | 20 | 8 | 2071 | 98 | 1973.1 |
| 16 | expected_improvement | 25 | 10 | 36 | 20 | 8 | 2003 | 62 | 1940.7 |
| 17 | expected_improvement | 15 | 0 | 20 | 20 | 8 | 2018 | 88 | 1930.2 |
| 18 | expected_improvement | 10 | 10 | 32 | 20 | 8 | 1998 | 59 | 1938.8 |
| 19 | expected_improvement | 10 | 0 | 32 | 20 | 8 | 1998 | 59 | 1938.8 |

Recommended candidate: `bboost_hold=10-freehit_hold=20-planning_hit_cost=8-threexc_hold=5-wildcard_hold=28` — a candidate for the next season chain and the gates, not a promotion. Measurement only; the 2025-26 holdout was not read.

# Bayesian search over chip holding values and planning hit cost (season chain)

- Contract `chip_bayesopt_v1` on `deterministic_policy_bo_v1`; seasons 2021-22, 2022-23, 2023-24, 2024-25; chip mode value; budget 20 (8 initial); 42 min.
- Objective: mean season net minus 1 x season standard deviation.

| Iteration | Phase | bboost | 3xc | wildcard | freehit | hit cost | Mean net | Spread | Robust |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | initial_design | 25 | 30 | 28 | 10 | 6 | 1984 | 58 | 1926.2 |
| 1 | initial_design | 0 | 0 | 0 | 0 | 4 | 1957 | 108 | 1848.4 |
| 2 | initial_design | 0 | 0 | 40 | 20 | 8 | 2042 | 67 | 1975.8 |
| 3 | initial_design | 30 | 0 | 0 | 0 | 8 | 2007 | 104 | 1902.9 |
| 4 | initial_design | 30 | 0 | 0 | 20 | 4 | 1980 | 130 | 1850.1 |
| 5 | initial_design | 0 | 25 | 0 | 0 | 8 | 2013 | 95 | 1917.6 |
| 6 | initial_design | 0 | 25 | 0 | 20 | 4 | 2012 | 127 | 1884.9 |
| 7 | initial_design | 30 | 0 | 40 | 0 | 4 | 1944 | 123 | 1821.4 |
| 8 | expected_improvement | 0 | 15 | 40 | 20 | 8 | 2040 | 65 | 1975.4 |
| 9 | expected_improvement | 10 | 10 | 40 | 20 | 8 | 2042 | 67 | 1975.8 |
| 10 | expected_improvement | 15 | 30 | 40 | 20 | 8 | 2032 | 61 | 1970.3 |
| 11 | expected_improvement | 5 | 30 | 40 | 10 | 8 | 1987 | 31 | 1956.3 |
| 12 | expected_improvement | 5 | 10 | 24 | 20 | 8 | 2038 | 63 | 1974.5 |
| 13 | expected_improvement | 10 | 30 | 20 | 20 | 8 | 2006 | 71 | 1935.9 |
| 14 | expected_improvement | 0 | 5 | 32 | 20 | 8 | 2063 | 50 | 2013.3 |
| 15 | expected_improvement | 0 | 0 | 24 | 20 | 8 | 2038 | 63 | 1974.5 |
| 16 | expected_improvement | 0 | 5 | 32 | 15 | 8 | 2014 | 90 | 1923.5 |
| 17 | expected_improvement | 30 | 30 | 40 | 0 | 8 | 1979 | 32 | 1946.4 |
| 18 | expected_improvement | 0 | 5 | 32 | 20 | 7 | 2065 | 47 | 2018.2 |
| 19 | expected_improvement | 0 | 10 | 32 | 20 | 7 | 2065 | 47 | 2018.2 |

Recommended candidate: `bboost_hold=0-freehit_hold=20-planning_hit_cost=7-threexc_hold=10-wildcard_hold=32` — a candidate for the next season chain and the gates, not a promotion. Measurement only; the 2025-26 holdout was not read.

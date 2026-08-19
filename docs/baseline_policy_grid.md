# Exhaustive deterministic policy grid

- Contract: `exhaustive_policy_grid_v1`
- Development folds: 147
- Grid size: 56 candidates, all evaluated
- Pinned risk_aversion: 0.0

**True optimum**: `bench_weight=0-form_window=10` with mean realized squad points 56.5034.

## Bayesian search measured against ground truth

- Search evaluated 16 of 56 candidates (29% of the grid)
- Recommendation: `bench_weight=0-form_window=10` (true rank 1)
- Regret: 0.0000 squad points
- Found the true optimum: True (iteration 3)
- Top-5 cells evaluated by the search: 4/5

This is measurement of a recommendation-only search. The locked holdout was
not accessed, nothing was promoted, and the operational control is unchanged.

## Complete ranking

| Rank | Candidate | form_window | bench_weight | Mean realized points |
| --- | --- | --- | --- | --- |
| 1 | `bench_weight=0-form_window=10` | 10 | 0.00 | 56.5034 |
| 2 | `bench_weight=0.05-form_window=10` | 10 | 0.05 | 56.1293 |
| 3 | `bench_weight=0.1-form_window=10` | 10 | 0.10 | 55.9796 |
| 4 | `bench_weight=0.2-form_window=10` | 10 | 0.20 | 55.8095 |
| 5 | `bench_weight=0.15-form_window=10` | 10 | 0.15 | 55.7007 |
| 6 | `bench_weight=0.25-form_window=10` | 10 | 0.25 | 55.5782 |
| 7 | `bench_weight=0.3-form_window=10` | 10 | 0.30 | 55.5510 |
| 8 | `bench_weight=0-form_window=9` | 9 | 0.00 | 55.4898 |
| 9 | `bench_weight=0-form_window=7` | 7 | 0.00 | 55.4694 |
| 10 | `bench_weight=0.05-form_window=9` | 9 | 0.05 | 55.3401 |
| 11 | `bench_weight=0.1-form_window=9` | 9 | 0.10 | 55.3197 |
| 12 | `bench_weight=0.3-form_window=9` | 9 | 0.30 | 55.1633 |
| 13 | `bench_weight=0.3-form_window=8` | 8 | 0.30 | 55.1565 |
| 14 | `bench_weight=0.15-form_window=9` | 9 | 0.15 | 55.1361 |
| 15 | `bench_weight=0.2-form_window=8` | 8 | 0.20 | 55.1224 |
| 16 | `bench_weight=0.25-form_window=9` | 9 | 0.25 | 55.0748 |
| 17 | `bench_weight=0.25-form_window=8` | 8 | 0.25 | 55.0204 |
| 18 | `bench_weight=0-form_window=8` | 8 | 0.00 | 55.0136 |
| 19 | `bench_weight=0.2-form_window=9` | 9 | 0.20 | 55.0136 |
| 20 | `bench_weight=0.05-form_window=7` | 7 | 0.05 | 54.9252 |
| 21 | `bench_weight=0.25-form_window=7` | 7 | 0.25 | 54.8639 |
| 22 | `bench_weight=0.3-form_window=7` | 7 | 0.30 | 54.8299 |
| 23 | `bench_weight=0.2-form_window=7` | 7 | 0.20 | 54.8231 |
| 24 | `bench_weight=0-form_window=6` | 6 | 0.00 | 54.7959 |
| 25 | `bench_weight=0.15-form_window=8` | 8 | 0.15 | 54.7959 |
| 26 | `bench_weight=0.1-form_window=7` | 7 | 0.10 | 54.7891 |
| 27 | `bench_weight=0.05-form_window=6` | 6 | 0.05 | 54.7551 |
| 28 | `bench_weight=0.05-form_window=8` | 8 | 0.05 | 54.7347 |
| 29 | `bench_weight=0.2-form_window=6` | 6 | 0.20 | 54.6871 |
| 30 | `bench_weight=0.1-form_window=8` | 8 | 0.10 | 54.6803 |
| 31 | `bench_weight=0.15-form_window=7` | 7 | 0.15 | 54.6667 |
| 32 | `bench_weight=0.15-form_window=6` | 6 | 0.15 | 54.6190 |
| 33 | `bench_weight=0.1-form_window=6` | 6 | 0.10 | 54.5986 |
| 34 | `bench_weight=0.25-form_window=6` | 6 | 0.25 | 54.5510 |
| 35 | `bench_weight=0.3-form_window=6` | 6 | 0.30 | 54.4694 |
| 36 | `bench_weight=0-form_window=5` | 5 | 0.00 | 54.2109 |
| 37 | `bench_weight=0.05-form_window=4` | 4 | 0.05 | 54.0748 |
| 38 | `bench_weight=0-form_window=4` | 4 | 0.00 | 54.0068 |
| 39 | `bench_weight=0.05-form_window=5` | 5 | 0.05 | 53.9660 |
| 40 | `bench_weight=0.25-form_window=5` | 5 | 0.25 | 53.9456 |
| 41 | `bench_weight=0.2-form_window=5` | 5 | 0.20 | 53.9048 |
| 42 | `bench_weight=0.2-form_window=4` | 4 | 0.20 | 53.8639 |
| 43 | `bench_weight=0.3-form_window=4` | 4 | 0.30 | 53.8435 |
| 44 | `bench_weight=0.15-form_window=4` | 4 | 0.15 | 53.8231 |
| 45 | `bench_weight=0.15-form_window=5` | 5 | 0.15 | 53.8231 |
| 46 | `bench_weight=0.25-form_window=4` | 4 | 0.25 | 53.7959 |
| 47 | `bench_weight=0.1-form_window=5` | 5 | 0.10 | 53.7755 |
| 48 | `bench_weight=0.1-form_window=4` | 4 | 0.10 | 53.7551 |
| 49 | `bench_weight=0.3-form_window=5` | 5 | 0.30 | 53.7075 |
| 50 | `bench_weight=0-form_window=3` | 3 | 0.00 | 51.2177 |
| 51 | `bench_weight=0.1-form_window=3` | 3 | 0.10 | 50.9864 |
| 52 | `bench_weight=0.05-form_window=3` | 3 | 0.05 | 50.9524 |
| 53 | `bench_weight=0.15-form_window=3` | 3 | 0.15 | 50.8503 |
| 54 | `bench_weight=0.25-form_window=3` | 3 | 0.25 | 50.7279 |
| 55 | `bench_weight=0.3-form_window=3` | 3 | 0.30 | 50.7075 |
| 56 | `bench_weight=0.2-form_window=3` | 3 | 0.20 | 50.6735 |

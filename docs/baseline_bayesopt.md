# Baseline deterministic policy search (Bayesian optimization)

- Objective contract: `baseline_policy_objective_v1`
- Development seasons: 2021-22, 2022-23, 2023-24, 2024-25
- Development folds: 147
- Search space: 56 candidates; evaluated 16
- Pinned risk_aversion: 0.0 (no scenario input in the deterministic evaluator)
- Stopped: evaluation_budget_exhausted
- Run fingerprint: `b0d7deb6210f9b567fdcfc4de73b8320665385594e49a126d9ece779e816524d`

**Recommended candidate**: `bench_weight=0-form_window=10` with mean realized squad points 56.5034.

This is a recommendation only. The locked holdout was not accessed, nothing
was promoted, and the operational control is unchanged.

| Iteration | Phase | Candidate | Mean realized points |
| --- | --- | --- | --- |
| 0 | initial_design | `bench_weight=0.25-form_window=9` | 55.0748 |
| 1 | initial_design | `bench_weight=0-form_window=3` | 51.2177 |
| 2 | initial_design | `bench_weight=0.3-form_window=3` | 50.7075 |
| 3 | initial_design | `bench_weight=0-form_window=10` | 56.5034 |
| 4 | initial_design | `bench_weight=0.15-form_window=5` | 53.8231 |
| 5 | initial_design | `bench_weight=0.05-form_window=7` | 54.9252 |
| 6 | expected_improvement | `bench_weight=0.1-form_window=10` | 55.9796 |
| 7 | expected_improvement | `bench_weight=0.05-form_window=10` | 56.1293 |
| 8 | expected_improvement | `bench_weight=0-form_window=9` | 55.4898 |
| 9 | expected_improvement | `bench_weight=0.3-form_window=10` | 55.5510 |
| 10 | expected_improvement | `bench_weight=0.2-form_window=10` | 55.8095 |
| 11 | expected_improvement | `bench_weight=0.15-form_window=8` | 54.7959 |
| 12 | expected_improvement | `bench_weight=0-form_window=4` | 54.0068 |
| 13 | expected_improvement | `bench_weight=0-form_window=6` | 54.7959 |
| 14 | expected_improvement | `bench_weight=0-form_window=5` | 54.2109 |
| 15 | expected_improvement | `bench_weight=0-form_window=7` | 55.4694 |

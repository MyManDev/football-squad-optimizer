# Scenario-aware policy search (Bayesian optimization)

- Objective contract: `scenario_policy_objective_v1`
- Evaluated seasons: 2024-25
- Evaluated folds: 37 (each fold's scenarios use only strictly earlier residual folds)
- Scenarios per fold: 100; tail fraction 0.1
- Candidate pool per position: top 20 projected + 8 cheapest (one rule for every candidate; pool sizes are fingerprinted)
- Per-fold solves stop at a wall-clock cap, not a deterministic work budget; this trace is recommendation-quality measurement, not a formal benchmark
- Search space: 616 candidates; evaluated 12
- Stopped: evaluation_budget_exhausted
- Run fingerprint: `eb189a6a33dfa489ce26f9c21bb98e4951166511692c29fa716dccadf094662b`

**Recommended candidate**: `bench_weight=0-form_window=6-risk_aversion=0` (form_window=6, bench_weight=0.0, risk_aversion=0.0) with mean realized squad points 57.1081.

`risk_aversion` is a live axis in this search: every decision was optimized
against an empirical scenario tail. This is a recommendation only — the
locked holdout was not accessed, nothing was promoted, and the operational
control is unchanged.

| Iteration | Phase | Candidate | Mean realized points |
| --- | --- | --- | --- |
| 0 | initial_design | `bench_weight=0.25-form_window=9-risk_aversion=0.6` | 44.7568 |
| 1 | initial_design | `bench_weight=0-form_window=3-risk_aversion=0` | 53.1622 |
| 2 | initial_design | `bench_weight=0.1-form_window=3-risk_aversion=1` | 19.5135 |
| 3 | initial_design | `bench_weight=0.3-form_window=3-risk_aversion=0.1` | 44.8919 |
| 4 | initial_design | `bench_weight=0-form_window=10-risk_aversion=0` | 54.8649 |
| 5 | expected_improvement | `bench_weight=0.2-form_window=10-risk_aversion=0` | 54.2432 |
| 6 | expected_improvement | `bench_weight=0-form_window=7-risk_aversion=0` | 56.0270 |
| 7 | expected_improvement | `bench_weight=0.1-form_window=8-risk_aversion=0` | 53.9730 |
| 8 | expected_improvement | `bench_weight=0.3-form_window=10-risk_aversion=0` | 54.7568 |
| 9 | expected_improvement | `bench_weight=0-form_window=6-risk_aversion=0` | 57.1081 |
| 10 | expected_improvement | `bench_weight=0-form_window=5-risk_aversion=0` | 56.0270 |
| 11 | expected_improvement | `bench_weight=0-form_window=10-risk_aversion=0.5` | 44.2973 |

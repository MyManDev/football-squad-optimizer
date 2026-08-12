# Real-data baseline benchmark

Generated at `2026-08-12T17:33:18+00:00` by `python -m scripts.run_baseline_benchmark`.
GW1 is intentionally evaluated by the separate opening-projection workflow.

## Provenance

- Repository commit: `3f219c57395237f1845bf0d82d8ac9c3a54865bb`
- Working tree dirty: `false`
- Archive: `vaastav/Fantasy-Premier-League@8c97b2adb123863c3dd581e730f1360e89815ac2`
- Manifest SHA-256: `fbe2e6a3e50d86c9d4a34bfa9cb51ee078e7dcd3d0dd9836bb72e9720cd1e717`
- Historical panel: `155995` rows
- Benchmark contract: `walk_forward_baseline_v1`
- Feature contract: `form_window_v1`

## Configuration

- Evaluation seasons: `2025-26`
- `form_window`: `5` completed matches
- `min_prior_gameweeks_in_season`: `1`
- Cross-season decay: `0.5`
- Cross-season minimum minutes: `270`

## Aggregate results

| Metric | Value |
| --- | ---: |
| Attempted folds | 37 |
| Feasible folds | 37 |
| Feasibility rate | 1.0 |
| Mean realized squad points | 46.72973 |
| Realized points stddev | 15.038057 |
| Minimum realized points | 25.0 |
| 25th percentile realized points | 32.0 |
| Median realized points | 46.0 |
| 75th percentile realized points | 57.0 |
| Maximum realized points | 77.0 |
| Mean projected objective | 93.024216 |
| Median solver runtime (s) | 0.796941 |
| P95 solver runtime (s) | 0.975861 |
| Mean squad turnover | 6.666667 |

## Fold results

| Fold | Status | Realized | Projected objective | Runtime (s) | Turnover |
| --- | --- | ---: | ---: | ---: | ---: |
| 2025-26-gw02 | OPTIMAL | 43.0 | 155.6 | 0.572052 | None |
| 2025-26-gw03 | OPTIMAL | 30.0 | 122.6 | 0.639992 | 10 |
| 2025-26-gw04 | OPTIMAL | 77.0 | 102.066 | 0.937089 | 8 |
| 2025-26-gw05 | OPTIMAL | 56.0 | 100.25 | 0.730314 | 3 |
| 2025-26-gw06 | OPTIMAL | 65.0 | 91.98 | 0.783804 | 5 |
| 2025-26-gw07 | OPTIMAL | 59.0 | 93.76 | 0.795741 | 7 |
| 2025-26-gw08 | OPTIMAL | 68.0 | 93.08 | 0.805078 | 4 |
| 2025-26-gw09 | OPTIMAL | 28.0 | 95.74 | 0.708056 | 5 |
| 2025-26-gw10 | OPTIMAL | 73.0 | 87.32 | 0.72461 | 7 |
| 2025-26-gw11 | OPTIMAL | 27.0 | 94.74 | 0.753381 | 6 |
| 2025-26-gw12 | OPTIMAL | 46.0 | 88.38 | 0.755741 | 7 |
| 2025-26-gw13 | OPTIMAL | 25.0 | 87.48 | 0.82312 | 6 |
| 2025-26-gw14 | OPTIMAL | 28.0 | 82.56 | 0.741548 | 10 |
| 2025-26-gw15 | OPTIMAL | 65.0 | 85.82 | 0.722606 | 9 |
| 2025-26-gw16 | OPTIMAL | 51.0 | 92.76 | 0.735262 | 5 |
| 2025-26-gw17 | OPTIMAL | 67.0 | 97.26 | 0.769928 | 9 |
| 2025-26-gw18 | OPTIMAL | 38.0 | 101.12 | 0.775861 | 7 |
| 2025-26-gw19 | OPTIMAL | 31.0 | 94.78 | 0.832791 | 4 |
| 2025-26-gw20 | OPTIMAL | 26.0 | 89.12 | 0.904759 | 7 |
| 2025-26-gw21 | OPTIMAL | 54.0 | 85.2 | 0.838426 | 5 |
| 2025-26-gw22 | OPTIMAL | 53.0 | 88.56 | 0.809596 | 7 |
| 2025-26-gw23 | OPTIMAL | 37.0 | 88.16 | 0.840805 | 5 |
| 2025-26-gw24 | OPTIMAL | 43.0 | 82.64 | 0.759713 | 6 |
| 2025-26-gw25 | OPTIMAL | 32.0 | 80.24 | 0.902378 | 6 |
| 2025-26-gw26 | OPTIMAL | 51.0 | 82.04 | 0.871894 | 10 |
| 2025-26-gw27 | OPTIMAL | 57.0 | 88.78 | 0.862439 | 9 |
| 2025-26-gw28 | OPTIMAL | 41.0 | 90.42 | 0.90189 | 6 |
| 2025-26-gw29 | OPTIMAL | 70.0 | 87.86 | 0.975861 | 7 |
| 2025-26-gw30 | OPTIMAL | 36.0 | 91.68 | 0.82194 | 4 |
| 2025-26-gw31 | OPTIMAL | 32.0 | 82.62 | 0.617654 | 9 |
| 2025-26-gw32 | OPTIMAL | 38.0 | 87.18 | 0.789286 | 10 |
| 2025-26-gw33 | OPTIMAL | 66.0 | 88.04 | 0.796941 | 10 |
| 2025-26-gw34 | OPTIMAL | 57.0 | 86.2 | 0.43626 | 6 |
| 2025-26-gw35 | OPTIMAL | 31.0 | 93.34 | 0.852413 | 7 |
| 2025-26-gw36 | OPTIMAL | 46.0 | 92.06 | 0.806885 | 4 |
| 2025-26-gw37 | OPTIMAL | 46.0 | 91.98 | 0.993818 | 7 |
| 2025-26-gw38 | OPTIMAL | 36.0 | 98.48 | 0.841212 | 3 |

## Environment

- Platform: `Windows-11-10.0.26200-SP0`
- Processor: `Intel64 Family 6 Model 183 Stepping 1, GenuineIntel`
- Logical CPUs: `32`
- Python: `3.13.5`
- pandas: `3.0.5`
- OR-Tools: `9.15.6755`

## Limitations

- Opening gameweeks are evaluated separately and are not included in these aggregates.
- The baseline is leakage-safe and explainable, not a predictive-accuracy claim.
- Automatic substitutions, vice-captain fallback, and bench points are excluded.
- Players without usable history retain the declared constant fallback.

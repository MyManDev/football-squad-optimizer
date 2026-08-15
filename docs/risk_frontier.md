# Risk-aversion frontier (mean versus downside)

- Contract: `risk_frontier_v1`
- Anchor policy: form_window=6, bench_weight=0.0
- Evaluated seasons: 2024-25; 37 folds
- Scenarios per fold: 100
- Downside metrics: lower 10% quantile, worst 10% tail mean, P(score < 40)
- Per-fold solves stop at a wall-clock cap; this is recommendation-quality measurement, not a formal benchmark

Each row answers: what does this risk-aversion level pay in mean points, and
what floor does it buy in return, against the risk-neutral baseline?

| risk_aversion | Mean | Stddev | Lower q | Worst-tail mean | P(bad week) | Mean premium | Floor gain |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0.0 | 57.11 | 16.61 | 37.00 | 33.50 | 0.16 | +0.00 | +0.00 |
| 0.1 | 42.32 | 14.89 | 27.00 | 19.25 | 0.43 | +14.78 | -10.00 |
| 0.2 | 44.49 | 15.53 | 25.00 | 23.50 | 0.46 | +12.62 | -12.00 |
| 0.3 | 44.35 | 15.95 | 25.00 | 19.50 | 0.41 | +12.76 | -12.00 |
| 0.4 | 42.35 | 15.30 | 24.00 | 21.25 | 0.43 | +14.76 | -13.00 |
| 0.5 | 43.05 | 15.56 | 18.00 | 17.50 | 0.46 | +14.05 | -19.00 |
| 0.6 | 42.70 | 16.08 | 24.00 | 20.25 | 0.46 | +14.41 | -13.00 |
| 0.7 | 43.24 | 16.59 | 25.00 | 19.25 | 0.49 | +13.86 | -12.00 |
| 0.8 | 41.86 | 14.60 | 23.00 | 19.75 | 0.46 | +15.24 | -14.00 |
| 0.9 | 39.46 | 13.58 | 21.00 | 19.50 | 0.54 | +17.65 | -16.00 |
| 1.0 | 19.24 | 8.57 | 9.00 | 8.25 | 0.97 | +37.86 | -28.00 |

Measurement only: the locked holdout was not accessed, nothing was promoted,
and the operational control is unchanged.

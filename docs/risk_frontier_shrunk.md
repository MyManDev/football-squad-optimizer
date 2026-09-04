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
| 0.0 | 55.05 | 17.51 | 31.00 | 29.25 | 0.22 | +0.00 | +0.00 |
| 0.2 | 39.30 | 15.69 | 21.00 | 18.00 | 0.57 | +15.76 | -10.00 |
| 0.4 | 39.19 | 15.84 | 23.00 | 19.50 | 0.59 | +15.86 | -8.00 |

Measurement only: the locked holdout was not accessed, nothing was promoted,
and the operational control is unchanged.

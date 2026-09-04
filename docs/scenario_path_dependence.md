# A window as one path, against a window as independent weeks

- Contract `hierarchical_residual_scenario_paths_v1`; 2024-25 from gameweek 20, horizon 3, 4000 scenarios, seed 7.
- 711 players, 128 historical folds of the operational control's own out-of-sample residuals.
- Both arms use the **same projection** every week, so nothing here is about the point estimate; only the sampling differs.

| | Mean player sd | Eleven mean | Eleven sd | p05 | p50 | p95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `path` | 3.7555 | 265.95 | 21.31 | 232.56 | 265.05 | 302.14 |
| `independent` | 3.8216 | 266.14 | 22.11 | 232.01 | 265.78 | 304.33 |

## What it says

Treating the window as one path **narrows** it: the mean player standard deviation is **0.9827x** the independent one, and the eleven's fifth-to-ninety-fifth spread is 69.59 against 72.32.

The direction is the finding. Persistence is often assumed to widen a window — a bad week followed by another bad week — and on the control's residuals it does the opposite by a small amount. A player who over-performs his projection one week tends to fall back the next, and that mean reversion cancels part of what independent draws would add up. The effect is small; what matters is that it is measured rather than asserted, and that it runs the other way from the intuition.

This is not an argument for independent weeks. Independence states a dependence structure the data does not have; a path states the one it does. The correction happens to be small here, and it would not be knowable without measuring.


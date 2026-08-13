# Sprint 3 Projection Uncertainty Specification

## Status and scope

This document defines the implemented Sprint 3 player-projection uncertainty contract.

Contract version: `projection_uncertainty_v1`.

The contract calibrates uncertainty around the existing deterministic point projection. It
does not change `expected_points`, fit a new prediction model, or change the CP-SAT
objective. Its output is the stable input boundary required by later scenario generation,
risk-aware optimization, and Bayesian Optimization work.

## Public interface

The importable API lives under `squadopt.uncertainty`:

```python
from squadopt.uncertainty import (
    UncertaintyConfig,
    apply_projection_uncertainty,
    evaluate_projection_uncertainty,
    fit_projection_uncertainty,
)

config = UncertaintyConfig()
calibration = fit_projection_uncertainty(development_folds, config)
calibrated = apply_projection_uncertainty(projections, calibration)
holdout = evaluate_projection_uncertainty(holdout_folds, calibration)
```

Configuration, calibration, fold result, metric, and evaluation records are frozen
dataclasses. Input DataFrames are copied and result DataFrames return independent copies.

## Time split and leakage boundary

The default split is fixed before calibration:

| Role | Seasons | Opening gameweek |
| --- | --- | --- |
| Development calibration | `2021-22` through `2024-25` | Excluded |
| Locked holdout evaluation | `2025-26` | Excluded |

Every input is an existing `EvaluationFold`. Its projection table was built at the decision
timestamp using only information available then; its realized table is joined afterwards by
exact `fold_id` and `player_id`. A missing or extra player is an error rather than an inner
join that silently changes the scoring population.

`fit_projection_uncertainty` accepts only configured development seasons and explicitly
rejects the configured holdout. `evaluate_projection_uncertainty` accepts only the frozen
calibration and configured holdout. Holdout outcomes affect coverage/error metrics but
cannot refit the radius, mean, standard deviation, group selection, or calibration
fingerprint. Synthetic mutation tests enforce this boundary.

Here, *locked* describes the enforced fit/evaluation API boundary. The `2025-26` season was
also used by earlier Sprint 1 and Sprint 2 benchmarks, so it is not a pristine final test
set. The uncertainty contract must not be tuned after observing these results. A genuinely
new external confirmation requires a future completed season, such as `2026-27`.

Gameweek 1 remains separate because it uses carry-over and the fitted opening-price prior,
not a within-season rolling projection.

## Residual and interval definition

For each development player-gameweek:

```text
residual_i = total_points_i - expected_points_i
nonconformity_i = abs(residual_i)
```

The default confidence level is `0.90`. For `n` calibration residuals, the one-based
finite-sample conformal rank is:

```text
k = min(n, ceil((n + 1) * confidence_level))
```

The interval radius is the `k`th ordered absolute residual. No interpolated percentile is
used. For a new point projection `mu_i`:

```text
lower_i = mu_i - radius_group(i)
upper_i = mu_i + radius_group(i)
```

Intervals are symmetric and marginal. The lower bound is not clamped to zero because
realized fantasy points can be negative. `expected_points` itself remains unchanged and
non-negative under the upstream projection contract.

The rank is the standard finite-sample conformal order statistic. A distribution-free
coverage guarantee additionally requires exchangeability between calibration and future
residuals within the effective group. Repeated players, adjacent gameweeks, and temporal
drift can violate that assumption, so the locked-season empirical coverage remains an
important diagnostic rather than a universal guarantee.

## Position conditioning and pooled fallback

Calibration is conditional on canonical position (`GK`, `DEF`, `MID`, `FWD`) when that
position has at least `min_group_observations` residuals. Otherwise it deterministically
uses the complete pooled residual distribution. Every calibrated row records:

- `expected_points_stddev`;
- `prediction_interval_lower`;
- `prediction_interval_upper`;
- `uncertainty_group`;
- `uncertainty_source` (`position` or `pooled_fallback`);
- `uncertainty_observations`.

The population standard deviation (`pstdev`) and residual mean are diagnostics. The
conformal radius—not a normal-distribution multiplier—constructs the prediction interval.

## Metrics

The holdout evaluator reports overall, per-position, and per-fold:

- observation count;
- empirical interval coverage;
- mean interval width;
- point-projection MAE;
- point-projection RMSE;
- mean residual/error.

Coverage is inclusive at both interval bounds. Metrics are player-level; they are not
squad-level realized-score confidence intervals.

## Real-data benchmark

Reproduce the pinned benchmark after fetching the historical archive:

```powershell
.venv\Scripts\python -m scripts.fetch_historical_data
.venv\Scripts\python -m scripts.run_uncertainty_benchmark
```

Generated JSON and Markdown reports remain under ignored `artifacts/sprint3/`.

Results on `vaastav/Fantasy-Premier-League@8c97b2a`:

| Population | Development n | Holdout n | Coverage | Mean width | MAE | RMSE |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| All | 101,447 | 28,648 | 0.908301 | 6.877004 | 1.058329 | 2.135163 |
| GK | 11,145 | 3,302 | 0.921563 | 5.600000 | 0.619801 | 1.562093 |
| DEF | 34,039 | 9,373 | 0.901739 | 7.600000 | 1.232623 | 2.342338 |
| MID | 43,826 | 12,811 | 0.907033 | 6.400000 | 1.029000 | 2.075750 |
| FWD | 12,437 | 3,162 | 0.919039 | 8.000000 | 1.118451 | 2.243975 |

All four positions exceed the default minimum group sample, so none uses pooled fallback
in this benchmark. The fallback remains part of the tested public contract for thinner
datasets.

## Validation and determinism

Validation rejects missing contract columns, duplicate columns or player IDs, empty frames,
mixed or inconsistent identifier types, invalid positions, non-finite point/outcome values,
negative expected points, incomplete player alignment, duplicate decisions, missing
configured development seasons, and any attempt to mix development and holdout roles.

Calibration contains no random sampling. Stable chronological fold order, stable player
sorting, a declared order statistic, immutable configuration, and SHA-256 fingerprints make
the same input/configuration reproducible.

The benchmark provenance also records the point-projection feature contract and the fixed
baseline `form_window=5` used to produce `expected_points`.

## Known limitations and later work

- Intervals are symmetric around a deterministic baseline and may be conservative or wide.
- Calibration is marginal per player; player dependence and cross-player correlation are
  not modeled.
- Residual non-stationarity inside a position is not modeled.
- Calibration does not distinguish home/away, opponent, expected minutes, or availability.
- Opening gameweeks are excluded.
- The `2025-26` evaluation season has been reused by earlier sprint benchmarks and must not
  be treated as a pristine final test set.
- Fold preparation is correct but currently expensive because full walk-forward projections
  are rebuilt before calibration; reusable persisted fold artifacts are future software work.
- Monte Carlo scenarios, risk penalties, risk-aware CP-SAT, Gaussian Processes, Bayesian
  Optimization, Markov models, and multi-gameweek planning remain out of scope.

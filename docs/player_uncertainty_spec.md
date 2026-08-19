# Sprint 5 Prediction Integration and Player-Adaptive Uncertainty Specification

## Status and scope

Sprint 5 implements two separate, composable contracts:

- prediction-to-optimization: `prediction_to_optimization_v1`;
- player-adaptive uncertainty: `player_adaptive_uncertainty_v1`;
- development screening: `player_risk_screening_v1`.

The implementation remains model-neutral. It does not train a learned point-prediction
model. The real-data benchmark routes the existing deterministic baseline through the new
boundary to test integration and provenance. A future model may produce the same prediction
contract without changing uncertainty calibration, risk optimization, or CP-SAT.

Monte Carlo scenarios, cross-player correlation, Gaussian Processes, Bayesian Optimization,
CVaR, reinforcement learning, and multi-gameweek planning are out of scope.

## Prediction-to-optimization boundary

An external model supplies exactly one prediction per deadline player using these contract
columns:

```text
player_id
expected_points
```

Additional model diagnostic columns may be present, but they are intentionally dropped at
the boundary and do not enter the optimizer table or its fingerprint.

`prepare_optimizer_projection` exact-aligns those values with the deadline-known snapshot:

```text
player_id, name, team_id, position, price_tenths
```

The returned `PredictionSnapshot` contains the canonical optimizer table, a SHA-256
prediction fingerprint, and `PredictionProvenance`:

```text
model_name
model_version
feature_contract_version
training_cutoff
training_data_fingerprint
contract_version
```

Missing or extra player IDs, duplicate IDs or columns, mixed ID types, invalid prices,
positions or points, and a tampered fingerprint are rejected. Inputs are deep-copied and
never modified in place. Stable player-ID sorting makes row order irrelevant to the
fingerprint. A walk-forward projection builder may return the snapshot directly; its model,
training, contract, and prediction fingerprints are copied into immutable fold metadata.

The boundary records what produced a prediction. It does not prove that an upstream model
used only permissible features; the training owner must set a truthful cutoff and data
fingerprint, and leakage tests remain required for that model.

## Chronological calibration split

For one target season, only completed earlier seasons are eligible. Ordered historical folds
are split once by `scale_training_fraction` (default `0.50`):

```text
earlier folds -> residual scale training
later folds   -> standardized conformal calibration
target folds  -> frozen decisions first, outcomes scored afterwards
```

Both fitting subsets must be non-empty and disjoint. Default screening uses:

| Target season | Eligible completed seasons |
| --- | --- |
| `2022-23` | `2021-22` |
| `2023-24` | `2021-22`, `2022-23` |
| `2024-25` | `2021-22`, `2022-23`, `2023-24` |

The reused `2025-26` benchmark is not loaded by the Sprint 5 command. Target-season outcomes
cannot affect that season's calibration, interval, risk coefficient, squad, XI, or captain.
They become eligible only after the season is complete and the next target begins.

## Player residual scale

For every scale-training player-gameweek:

```text
residual_it = total_points_it - expected_points_it
```

Population residual standard deviations are estimated for the pooled population, each
position, and each stable player ID. All applied scales have the configured positive
`minimum_scale`. If player `i` has at least `min_player_observations`, its variance is shrunk
toward the current position fallback scale:

```text
local_scale_i = sqrt(
    (n_i * player_scale_i^2 + k * position_scale_i^2) / (n_i + k)
)
```

where `k = shrinkage_observations`. This is deterministic partial pooling, not a posterior
distribution. If player history is insufficient, the position scale is used when supported;
otherwise the pooled scale is used.

Application rows declare one of:

- `player_shrunk`;
- `position_fallback`;
- `pooled_fallback`.

`player_uncertainty_observations` records raw player history. The existing
`uncertainty_observations` records the effective scale source count consumed by downstream
validation.

## Standardized split-conformal interval

The disjoint conformal subset uses the already-frozen scale function:

```text
score_it = abs(residual_it) / local_scale_it
```

For confidence level `coverage` and `n` effective scores, the one-based finite-sample rank is:

```text
rank = min(n, ceil((n + 1) * coverage))
```

Each position uses its own multiplier when it has at least
`min_position_observations`; otherwise it uses the pooled multiplier. For a later point
projection `mu_i`:

```text
radius_i = conformal_multiplier_position(i) * local_scale_i
lower_i  = mu_i - radius_i
upper_i  = mu_i + radius_i
```

`expected_points` is unchanged and lower bounds are not clamped. Intervals remain marginal;
finite-sample coverage interpretation still depends on exchangeability, which repeated
players, temporal drift, injuries, and changing roles can violate.

## Public interface

```python
from squadopt.prediction import PredictionProvenance, prepare_optimizer_projection
from squadopt.uncertainty import (
    PlayerAdaptiveUncertaintyConfig,
    apply_player_adaptive_uncertainty,
    evaluate_player_adaptive_uncertainty,
    fit_player_adaptive_uncertainty,
)

snapshot = prepare_optimizer_projection(player_snapshot, model_predictions, provenance)
config = PlayerAdaptiveUncertaintyConfig()
calibration = fit_player_adaptive_uncertainty(development_folds, config)
calibrated = apply_player_adaptive_uncertainty(snapshot.table, calibration)
evaluation = evaluate_player_adaptive_uncertainty(holdout_folds, calibration)
```

The existing `optimize_risk_aware_squad` consumes the calibrated result. Its lower-bound
formula and CP-SAT feasible set are unchanged. `risk_aversion=0` remains the point-objective
control; greater values can now distinguish players in the same position.

## Development screening and reproduction

`run_player_risk_screening` uses the same fixed risk candidates and paired diagnostics as
Sprint 4, but fits `player_adaptive_uncertainty_v1` before each target season. It reports
mean and downside realized scores, exact-fold differences, feasibility, and squad/XI/captain
changes. These are diagnostics only; there is no automatic promotion threshold or selected
winner.

```powershell
.venv\Scripts\python -m scripts.fetch_historical_data
.venv\Scripts\python -m scripts.run_player_risk_screening
```

Strict JSON and Markdown reports are generated under ignored `artifacts/sprint5/`. Provenance
includes the pinned archive commit and manifest hash, repository state, environment,
prediction fingerprint per fold, feature contract, screening configuration, and calibration
fingerprint per decision.

The first complete pinned run prepared 147 provenanced folds and evaluated 110 paired folds
over `2022-23` through `2024-25`. Every CP-SAT solve was `OPTIMAL`:

| Risk aversion | Mean score | Stddev | 10% quantile | Mean worst 10% | Mean vs control | Squad/XI/captain changes |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.00 | 53.518182 | 16.458616 | 34.000000 | 29.454545 | 0.000000 | 0/0/0 |
| 0.25 | 52.436364 | 16.534002 | 33.000000 | 29.000000 | -1.081818 | 89/91/16 |
| 0.50 | 52.163636 | 16.836393 | 30.000000 | 25.818182 | -1.354545 | 106/110/29 |
| 1.00 | 49.490909 | 16.255206 | 31.000000 | 25.181818 | -4.027273 | 110/110/50 |

Player-adaptive penalties materially change same-position decisions, unlike the Sprint 4
position-only signal. None of the risk-averse candidates improves the declared development
mean or downside summaries, so this result supplies no promotion evidence and the
`risk_aversion=0` control remains the operational default. The run took 709.5 seconds on the
recorded local Windows environment; runtime is hardware-sensitive.

## Validation and determinism

Validation rejects malformed configs, insufficient folds or residual counts, overlapping
scale/conformal subsets, inconsistent IDs, missing positions, non-finite values, invalid
learned state, and fingerprint tampering. Synthetic mutation tests verify that target
outcomes cannot change same-season decisions.

The pipeline uses chronological fold ordering, stable player-ID sorting, exact alignment,
finite-sample order statistics, immutable configs, SHA-256 fingerprints, integer CP-SAT
coefficients, one solver worker, and the declared deterministic seed.

## Known limitations

- The real-data Sprint 5 benchmark still uses the deterministic baseline point projection.
- Sparse players rely heavily on shrinkage or fallback; the effective source is explicit.
- Residual scale is historical and does not directly condition on opponent, availability,
  role change, or forecast playing time.
- Intervals are symmetric and marginal, not a joint squad distribution or portfolio bound.
- Cross-player and cross-gameweek dependence is not modeled.
- Opening gameweeks remain outside within-season residual screening.
- Development screening is not a pristine final test and cannot justify promotion by itself.

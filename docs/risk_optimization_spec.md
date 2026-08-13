# Sprint 4 Conformal Risk Optimization Specification

## Status and scope

This document defines the implemented Sprint 4 risk-aware single-gameweek decision
contract. It consumes the frozen Sprint 3 projection-uncertainty output without fitting a
new prediction model or inventing a probability distribution.

Contract versions:

- objective: `conformal_lcb_objective_v1`;
- screening: `rolling_risk_screening_v1`.

The Sprint 0 feasible set is unchanged. Budget, squad and starting sizes, position quotas,
formation bounds, team limits, and captain constraints remain identical.

## Public interface

```python
from squadopt.risk import (
    RiskOptimizationConfig,
    RiskScreeningConfig,
    optimize_risk_aware_squad,
    run_risk_screening,
)

risk = RiskOptimizationConfig(risk_aversion=0.5)
decision = optimize_risk_aware_squad(
    calibrated_projection_result,
    optimization_config,
    risk,
)

screening = run_risk_screening(prepared_folds, RiskScreeningConfig())
```

The input to `optimize_risk_aware_squad` is a `CalibratedProjectionResult`, not a raw
DataFrame. This preserves the calibration fingerprint and makes the uncertainty provenance
part of every risk decision.

## Risk-adjusted projection

For player `i`, let:

```text
mu_i = expected_points_i
L_i  = prediction_interval_lower_i
lambda in [0, 1] = risk_aversion
```

The objective projection is:

```text
q_i(lambda) = mu_i - lambda * (mu_i - L_i)
            = (1 - lambda) * mu_i + lambda * L_i
```

Therefore:

- `lambda=0` is exactly the existing risk-neutral point objective;
- `lambda=1` uses the complete conformal lower bound;
- intermediate values are convex blends.

The calculation uses `Decimal(str(value))`. CP-SAT receives the same
`expected_points_scale` and `ROUND_HALF_UP` coefficient rule as the baseline optimizer.
Negative `q_i` values are valid because conformal lower bounds and realized fantasy points
may be negative.

## Optimization objective

Let `r_i` be the scaled integer representation of `q_i(lambda)` and `b_i` its scaled bench
coefficient. The constraints and binary variables `x_i`, `s_i`, and `c_i` are unchanged.
Sprint 4 maximizes:

```text
sum_i r_i * s_i
+ sum_i r_i * c_i
+ sum_i b_i * (x_i - s_i)
```

`projected_score` in the underlying `OptimizationResult` still uses original
`expected_points`. The wrapper separately reports the risk-adjusted projected score, the
expected-points objective for the chosen decision, the risk-adjusted objective, and their
difference as `risk_penalty_value`.

This penalty is a deterministic objective adjustment. It is not the probability of a loss,
a joint squad confidence bound, Value at Risk, or Conditional Value at Risk.

## Validation and determinism

Validation requires the complete Sprint 3 calibrated table contract. It rejects missing or
duplicate columns, invalid calibration fingerprints, intervals that do not contain the point
projection, negative standard deviations, inconsistent uncertainty groups/sources, invalid
observation counts, duplicate players, and non-finite adjusted values.

The baseline optimizer public interface is unchanged. Both paths use one shared CP-SAT
implementation, one worker, the declared deterministic seed, integer coefficients, and the
existing stable player-ID tie-break. Synthetic tests prove that `lambda=0` returns the same
squad, XI, and captain as `optimize_squad`.

## Expanding-season leakage boundary

Risk levels are screened only on the configured development seasons:

| Target season | Calibration residual seasons |
| --- | --- |
| `2022-23` | `2021-22` |
| `2023-24` | `2021-22`, `2022-23` |
| `2024-25` | `2021-22`, `2022-23`, `2023-24` |

For each target season, calibration is fitted before its outcomes are scored. Target-season
outcomes cannot affect that season's interval, risk coefficients, squad, XI, or captain.
After a season is complete, it becomes eligible calibration history for the next season.

The reused `2025-26` benchmark is not accessed. Sprint 4 produces development diagnostics
and performs no candidate promotion. A future completed season is required for a new final
confirmation.

## Screening design and metrics

The pre-registered levels are:

```text
risk_aversion in {0.0, 0.25, 0.5, 1.0}
```

`risk_aversion=0` is the control. Every level is evaluated on the same exact fold sequence.
The report includes:

- feasibility and scored-fold counts;
- mean and population standard deviation of realized squad score;
- nearest-rank 10th-percentile score;
- mean of the lowest `ceil(0.10 * n)` scores;
- minimum realized score;
- mean expected and risk-adjusted objectives;
- mean risk penalty;
- exact-fold paired score differences against the control;
- counts of changed squad, starting-XI, and captain decisions.

These are descriptive diagnostics. No promotion threshold is applied because there is no
unused final holdout.

## Real-data screening result

The pinned development screening produced 110 paired folds over `2022-23`, `2023-24`, and
`2024-25`:

| Risk aversion | Mean score | Stddev | 10% quantile | Mean worst 10% | Mean vs control | Squad/XI/captain changes |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.00 | 53.518182 | 16.458616 | 34.000000 | 29.454545 | 0.000000 | 0/0/0 |
| 0.25 | 53.309091 | 16.324408 | 34.000000 | 29.454545 | -0.209091 | 3/5/1 |
| 0.50 | 53.290909 | 16.396976 | 33.000000 | 29.000000 | -0.227273 | 4/16/3 |
| 1.00 | 53.336364 | 16.400265 | 33.000000 | 28.727273 | -0.181818 | 10/27/8 |

All candidates were feasible on every fold. None improved mean score or the declared
downside summaries relative to `risk_aversion=0`. The result supports retaining the
risk-neutral control as the current operational default, but no formal promotion decision is
made from this development-only evidence.

## Structural limitation of the current uncertainty signal

Sprint 3 estimates one conformal radius per position, with a pooled fallback for thin
positions. Consequently, the risk penalty is equal for players in the same effective group.
It does not by itself reorder two players in the same position. It can still affect
formation, captaincy, and coupled budget/team decisions across positions, but it is not yet
player-specific risk.

This limitation is why Sprint 4 does not claim portfolio uncertainty and does not generate
Monte Carlo draws from the interval. A conformal interval does not define a probability
distribution, and the current contract contains no cross-player dependence model.

## Reproduction

```powershell
.venv\Scripts\python -m scripts.fetch_historical_data
.venv\Scripts\python -m scripts.run_risk_screening
```

Generated JSON and Markdown reports remain under ignored `artifacts/sprint4/`.
The first complete local run took approximately 16 minutes on the recorded Windows
environment. Runtime is hardware-sensitive; reusable fold artifacts, solve caching, and
bounded candidate-level parallelism remain performance follow-up work.

## Out of scope

- Monte Carlo scenario generation;
- player-specific residual distributions and correlations;
- Gaussian Processes and Bayesian Optimization;
- Markov or reinforcement-learning models;
- CVaR or stochastic-programming objectives;
- multi-gameweek transfers, chips, and planning;
- fixture and availability feature engineering.

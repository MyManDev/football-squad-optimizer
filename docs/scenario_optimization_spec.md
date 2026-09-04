# Scenario-aware optimization specification

Status: **Sprint 13 implemented contract**.

This layer chooses one gameweek's squad, starting XI, bench, and captain directly against
the joint point scenarios produced by `ScenarioSet`. It is a stochastic optimization over
one shared decision. It does not solve a different squad inside every scenario.

## Public interface

```python
optimize_scenario_aware_squad(
    scenarios: ScenarioSet,
    optimization_config: OptimizationConfig,
    scenario_config: ScenarioOptimizationConfig | None = None,
) -> ScenarioOptimizationResult
```

`ScenarioOptimizationResult` contains the ordinary structured `OptimizationResult`, the
fixed-decision scenario evaluation, mean scenario score, empirical lower-tail CVaR, mean
bench score, blended objective value, risk penalty, solver status through the nested result,
and reproducibility diagnostics.

## Decision variables and feasible set

The binary decisions are unchanged from the baseline:

- `x_i`: player `i` belongs to the squad;
- `s_i`: player `i` starts;
- `c_i`: player `i` is captain.

Every Sprint 0 constraint is added through the same internal constraint builder: squad and
starting sizes, position quotas and formation bounds, budget, team limit, `s_i <= x_i`,
`c_i <= s_i`, and exactly one captain. Scenario-aware optimization changes the objective,
not the meaning of a legal squad.

## Score definitions

For scenario `k`, with simulated player points `p_ki`:

```text
Y_k = sum_i p_ki * s_i + sum_i p_ki * c_i
B_k = sum_i p_ki * (x_i - s_i)
```

`Y_k` is the realized starting-XI score with the captain counted for a second time. `B_k` is
bench quality. Bench points are not treated as realized team points; their expectation is a
separate squad-depth term.

For risk aversion `rho`, lower-tail fraction `alpha`, and baseline bench weight `w_b`, the
objective is:

```text
maximize (1 - rho) * mean(Y)
       + rho * empirical_CVaR_alpha(Y)
       + w_b * mean(B)
```

The empirical tail contains:

```text
K = ceil(alpha * scenario_count)
```

scenarios. The reported CVaR is the arithmetic mean of the `K` lowest fixed-decision scores.

## Linear CVaR formulation

The maximization form introduces integer `eta` and non-negative shortfalls `u_k`:

```text
u_k >= eta - Y_k
u_k >= 0

CVaR = eta - (1 / K) * sum_k u_k
```

At an optimum, this equals the mean of the `K` lowest empirical scores, including ties at the
boundary through the standard linear representation.

## Integer scaling

Scenario player points use `OptimizationConfig.expected_points_scale` and `ROUND_HALF_UP`,
the same rule as the baseline. Objective weights use
`ScenarioOptimizationConfig.objective_weight_scale`, also with `ROUND_HALF_UP`.

Let `W` be the objective weight scale, `R = round(rho * W)`, `N` the scenario count, `K` the
tail count, and `Q = round(w_b * W)`. CP-SAT maximizes the following integer-equivalent
objective:

```text
(W - R) * K * sum_k Y_k
+ R * N * K * eta
- R * N * sum_k u_k
+ Q * K * sum_k B_k
```

Dividing by `W * N * K * expected_points_scale` restores point units. A conservative bound
is checked before solving so coefficient growth cannot exceed the safe CP-SAT integer range.

## Determinism and validation

- `ScenarioSet` is revalidated, including its exact player alignment and fingerprint.
- Projection and scenario inputs are never mutated.
- Players are sorted by stable `player_id` before variables are created.
- CP-SAT uses one worker and the configured deterministic seed.
- A second solve fixes the proven primary optimum and applies the baseline deterministic
  squad/starting/captain rank tie-break.
- `OPTIMAL`, `FEASIBLE`, `INFEASIBLE`, and `UNKNOWN` remain solver-independent statuses.
- Negative scenario points are valid. Missing or non-finite scenario values are rejected by
  `ScenarioSet` before this layer runs.

## Interpretation

`rho = 0` maximizes scenario mean plus expected bench quality. If every scenario equals the
point projection, it reproduces the baseline decision exactly. `rho = 1` maximizes empirical
lower-tail CVaR plus expected bench quality. Intermediate values form a declared convex blend.

This objective should be screened on chronological development folds before becoming an
operational default. A single attractive live squad is not evidence for selecting `rho` or
`alpha`.

## Current limitations

- One gameweek only; transfer continuity belongs to Sprint 14.
- No chips, automatic substitutions, or vice-captain realization.
- Scenarios are equally weighted.
- The empirical scenario matrix is treated as supplied; this layer does not recalibrate it.
- CVaR protects total starting score, not individual players independently.
- Large scenario counts increase CP-SAT model size and integer coefficients; the safe-integer
  guard fails explicitly rather than weakening the objective.

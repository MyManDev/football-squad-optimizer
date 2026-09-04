# Sprint 7 Monte Carlo Scenario Specification

## Status and scope

Contract versions:

- scenario generation: `hierarchical_residual_scenarios_v1`;
- fixed-decision evaluation: `fixed_decision_scenario_evaluation_v1`.

Sprint 7 converts historical out-of-sample player residuals into reproducible joint outcome
scenarios and evaluates one already-frozen squad decision over that distribution. It builds
on Sprint 6's prediction provenance and residual schema without changing expected points or
the Sprint 0 optimizer.

It does not implement a scenario-aware objective, CVaR optimization, automatic candidate
promotion, fixture features, multi-gameweek planning, Bayesian Optimization, Gaussian
Processes, Markov models, or reinforcement learning. A stochastic optimizer belongs in a
later sprint after this scenario contract is reviewed.

## Public interfaces

```python
from squadopt.scenarios import (
    ScenarioConfig,
    ScenarioEvaluationConfig,
    ScenarioSet,
    ScenarioTarget,
    evaluate_fixed_decision,
    generate_scenarios,
)

scenarios = generate_scenarios(prediction_snapshot, residual_history, target)
evaluation = evaluate_fixed_decision(optimization_result, scenarios)
```

`ScenarioSet` contains:

- the independently validated `PredictionSnapshot`;
- target season and gameweek;
- ordered deterministic scenario IDs;
- one sampled source fold ID per scenario;
- a scenario-by-player `float64` matrix exact-aligned to projection player IDs;
- a SHA-256 fingerprint;
- fallback and component diagnostics.

The matrix may contain negative fantasy points. Real players can score negative points, so
clamping simulated outcomes would erase a genuine downside. The canonical point projection
remains non-negative and unchanged.

## Residual input contract

The required columns are:

```text
fold_id, season, gameweek, player_id, team_id, position,
predicted_points, realized_points, residual
```

Every row is an out-of-sample player prediction from a completed historical fold, and:

```text
residual = realized_points - predicted_points
```

The validator requires finite numeric values, exact fold IDs, unique `(fold_id, player_id)`
keys, canonical positions, identifier types matching the target projections, and a declared
minimum number of historical folds. Every residual fold must be strictly before the target.
Target or future residuals raise `ScenarioValidationError` rather than being silently
dropped.

Sprint 6 exposes `build_residual_history` so prediction and scenario owners share one table
definition instead of independently reconstructing residuals.

## Hierarchical empirical decomposition

For player `i`, team `k`, and historical fold `t`, let the OOS residual be `r_tki`.
The implementation decomposes it as:

```text
g_t     = mean_i(r_tki)
h_tk    = mean_{i in team k}(r_tki - g_t)
e_tki   = r_tki - g_t - h_tk
```

`g_t` is the common gameweek component, `h_tk` is the team-within-gameweek component, and
`e_tki` is the idiosyncratic component. Component pools are empirically centered so the
point projection remains the scenario distribution's intended center rather than having
historical mean error added a second time.

For each scenario:

1. one historical source fold is sampled with replacement;
2. its centered common component is used by every target player;
3. each target team samples a centered team component from that same source fold, and every
   player on that target team shares the draw;
4. each target player independently samples an empirical standardized idiosyncratic draw and
   multiplies it by their effective local scale.

This creates positive cross-player dependence from the common component and additional
within-team dependence from the team component. It is not a multivariate normal model and
does not claim that residuals are stationary indefinitely.

## Player-adaptive scale and fallback

For a target player with at least `min_player_observations`, let `n_i` be their historical
idiosyncratic count, `s_i` their population standard deviation, `s_p` their position scale,
and `lambda` the declared shrinkage strength. The effective variance is:

```text
effective_variance_i =
    (n_i * s_i^2 + lambda * s_p^2) / (n_i + lambda)
```

The player empirical standardized pool supplies shape and the shrunk scale supplies size.
When player history is thin, the position pool and scale are used. If that position also has
zero empirical variation, the pooled idiosyncratic distribution is the final fallback.
Diagnostics report player, position, and pooled fallback counts plus every target player's
effective scale.

## Determinism and fingerprint

The default `numpy.random.Generator` seed is `0`. Target players use the deterministic
projection order, folds use chronological order, target teams use first appearance in that
player order, and every random choice occurs in a fixed sequence.

The scenario SHA-256 covers:

- contract version and target fold;
- prediction fingerprint;
- all scenario controls and seed;
- scenario IDs and sampled source fold IDs;
- typed player IDs in matrix order;
- exact little-endian `float64` matrix bytes.

Identical content and seed produce identical matrices and fingerprints even if input residual
rows arrive in a different order. A changed seed changes both. `validated_copy` detects
mutation of either the scenario matrix or underlying prediction snapshot.

## Fixed-decision evaluation

`evaluate_fixed_decision` requires an `OPTIMAL` or `FEASIBLE` `OptimizationResult`. For
scenario `s`, it scores:

```text
score_s = sum_{i in starting XI}(points_si) + points_s,captain
```

The captain is therefore counted twice, matching the existing realized-score policy. Bench
points, vice-captain fallback, and automatic substitutions are excluded. The decision is not
reoptimized per scenario.

The default summaries are:

- mean score;
- population standard deviation;
- linearly interpolated lower 10% quantile;
- mean of the worst 10%, using `ceil(0.10 * scenario_count)` observations;
- minimum score;
- strict probability that score is below 40 points.

`ScenarioEvaluationConfig` makes the quantile, worst fraction, and threshold explicit.

## Real-data smoke benchmark

Run:

```powershell
.venv\Scripts\python -m scripts.run_scenario_benchmark
```

The pinned smoke benchmark uses `2024-25` learned OOS residuals from GW2 through GW9 and
targets GW10. It rejects the locked `2025-26` holdout. The verified run generated 2,000
scenarios in an end-to-end runtime of approximately 49.4 seconds and recorded:

| Metric | Value |
| --- | ---: |
| Historical residual rows | 5,262 |
| Historical folds | 8 |
| Target players | 674 |
| Player-scale source | 627 |
| Position fallback | 47 |
| Pooled fallback | 0 |
| Point-projection score | 57.5395 |
| Scenario mean | 57.2937 |
| Population standard deviation | 11.8587 |
| Lower 10% quantile | 42.6896 |
| Mean worst 10% | 37.1641 |
| Minimum | 19.0166 |
| P(score < 40) | 0.066 |

Artifacts are written under ignored `artifacts/sprint7/` as JSON and Markdown. The JSON
contains the prediction, data-source, scenario, decision, and seed provenance. Large scenario
matrices remain programmatic `ScenarioSet` values rather than being embedded in the summary
artifact.

## Assumptions and limitations

- The historical OOS residual process is informative for the next target gameweek.
- Team IDs need not be stable across seasons because historical team components are sampled
  as exchangeable team-within-fold effects.
- Eight smoke folds demonstrate integration but are not a definitive calibration horizon.
- Player/team dependence is empirical and hierarchical; opponent and fixture relationships
  are absent from the current canonical data.
- The sample mean only approximates the point projection at finite scenario count.
- Scenario count is not a Bayesian posterior sample count and has no GP interpretation.
- No scenario candidate is automatically accepted or promoted.

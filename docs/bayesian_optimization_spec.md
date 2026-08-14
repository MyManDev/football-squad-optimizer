# Bayesian policy-search specification

Status: **Sprint 15 implementation complete**.

This layer searches expensive, versioned policy configurations on chronological development
folds. It recommends a candidate; it does not promote that candidate, open the locked holdout,
or alter production configuration.

## Public interface

```python
run_bayesian_optimization(
    evaluator: ObjectiveEvaluator,
    development_fold_ids: tuple[str, ...],
    config: BayesianOptimizationConfig | None = None,
    *,
    locked_holdout_fold_ids: tuple[str, ...] = (),
) -> BayesianOptimizationResult
```

The evaluator receives exactly `(candidate, development_fold_ids)`. Locked-holdout IDs may be
recorded to prove role separation, but they are never passed to the evaluator. Development and
holdout identifiers must be disjoint.

The caller adapts the existing chronological experiment objective to this small callback. This
keeps the surrogate independent of prediction, optimization, and scenario implementation while
preserving the existing fold and objective contracts.

## Search-space contract

`BayesianFactor` defines:

- a unique factor name;
- lower and upper bounds;
- an exact quantization step;
- integer or continuous representation.

The step must land exactly on the upper bound. The resulting finite grid makes candidate
identity, caching, tie-breaking, and exhaustive verification unambiguous. Default factors are:

```text
form_window:    integer 3..10, step 1
bench_weight:   0.00..0.30, step 0.05
risk_aversion:  0.00..1.00, step 0.10
```

The default grid contains 616 canonical candidates. It does not imply that these ranges have
been promoted for production; they remain an experiment contract.

## Initial design

The first candidate is drawn from a seeded NumPy generator. Each subsequent initial candidate
maximizes its minimum Euclidean distance from the selected points after every factor is scaled
to `[0, 1]`. Exact distance ties use `candidate_id`.

This seeded maximin design is deterministic and space-filling without introducing an additional
sampling dependency.

## Gaussian-process surrogate

The implementation uses scikit-learn `GaussianProcessRegressor` with:

```text
kernel = fixed ConstantKernel(1.0) * fixed Matern(length_scale, nu)
normalize_y = True
alpha = observation_noise
kernel optimizer = None
```

Fixed hyperparameters prevent a hidden, optimizer-dependent inner search. The config and result
record the kernel controls, observation noise, seed, and contract fingerprint. Supported Matern
`nu` values are 0.5, 1.5, and 2.5.

## Acquisition

For predicted mean `mu(x)`, standard deviation `sigma(x)`, current best `f_best`, and exploration
offset `xi`, maximization Expected Improvement is:

```text
I(x) = mu(x) - f_best - xi
z(x) = I(x) / sigma(x)
EI(x) = I(x) * Phi(z) + sigma(x) * phi(z)
```

Zero-variance candidates use `max(I(x), 0)`. Every acquisition step scores all remaining grid
candidates, selects the largest EI, and breaks numerical ties by `candidate_id`.

## Budget, caching, and stopping

- Every canonical candidate is evaluated at most once.
- The evaluation cache is keyed by stable `candidate_id`.
- Search stops at `evaluation_budget`, exhaustion of the finite grid, or the declared
  `min_expected_improvement` threshold.
- Non-finite objective values and evaluator failures raise explicit domain errors.

The result contains the complete evaluated trace, including phase, objective value, selected
candidate, GP prediction, uncertainty, and EI where applicable.

## Recommendation and promotion boundary

The best observed candidate is selected by objective value, then `candidate_id` for exact ties.
Diagnostics explicitly state:

```text
locked_holdout_accessed = False
automatic_promotion = False
recommendation_only = True
```

Promotion gates, Ridge/control comparisons, and a single locked-holdout decision remain separate
workflow steps. Bayesian Optimization must never repeatedly query the locked holdout.

## Current limitations

- The search space is a finite quantized grid rather than unconstrained continuous optimization.
- The GP kernel hyperparameters are fixed, not estimated by marginal likelihood.
- The objective is scalar; Pareto or constrained multi-objective BO is excluded.
- Parallel/batch acquisition and asynchronous evaluations are not implemented.
- Production tuning still requires a caller-owned adapter from the existing chronological
  development-fold runner to the deliberately narrow evaluator callback. The optimizer itself
  never constructs folds or changes the recorded evaluation objective.
- Reinforcement learning and online adaptation remain out of scope.

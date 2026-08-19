# Sprint 6 Learned Prediction Specification

## Status and scope

Contract versions:

- model: `ridge-reference-v1`;
- learned feature matrix: `ridge-features-v1`;
- paired benchmark: `learned_vs_baseline_v1`;
- optimizer hand-off: `prediction_to_optimization_v1`.

Sprint 6 implements a small open-source learned projection reference and compares it with
the deterministic baseline on identical chronological folds. Its purpose is to prove the
training, provenance, prediction, optimization, and residual-history integration before the
data owner supplies a production model.

It does not implement fixture features, hyperparameter search, automatic model promotion,
Monte Carlo scenarios, scenario-aware optimization, Bayesian Optimization, Gaussian
Processes, Markov models, reinforcement learning, or multi-gameweek transfer planning.

## Public interfaces

The prediction package exposes:

```python
from squadopt.prediction import (
    FittedRidgePredictor,
    RidgeProjectionConfig,
    fit_ridge_predictor,
    predict_ridge_expected_points,
)
```

The walk-forward package exposes:

```python
from squadopt.backtest import (
    LearnedBenchmarkConfig,
    build_ridge_prediction_snapshot,
    make_ridge_projection_builder,
    run_learned_benchmark,
)
```

`FittedRidgePredictor` contains only frozen numeric state and fingerprints. A scikit-learn
estimator is never part of the public result. `build_ridge_prediction_snapshot` returns the
existing optimizer-neutral `PredictionSnapshot`, including exact player alignment and model,
feature, training-cutoff, training-data, fitted-model, and prediction identities.

## Feature matrix

For configured form window `w`, the numeric features are:

```text
price_tenths
minutes_last_w
points_last_w
points_per_90_last_w
prior_seasons_minutes_per_gameweek
prior_seasons_points_per_90
```

Four fixed indicators complete the matrix:

```text
position_GK, position_DEF, position_MID, position_FWD
```

`player_id`, `team_id`, and `name` are not treated as numeric model features. Current
gameweek outcome fields never enter the matrix. Within-season form columns use the existing
grouped shift-before-roll primitive. Carry-over reads completed earlier seasons only.

## Missing values and scaling

For each numeric matrix column, missing values are replaced by the median learned from the
current fold's training rows. If every training value in a column is missing, the declared
fallback is zero. Position indicators are complete by contract.

The imputed training matrix is standardized with its population mean and population standard
deviation. A constant feature receives scale `1`. The target matrix uses the stored training
imputation, center, and scale; no target or future statistic is read.

## Ridge formulation

Let `z_i` be the standardized feature vector and `y_i` the realized fantasy points for a
historical player-gameweek. The reference fits an intercept `b` and coefficients `beta`:

```text
minimize  sum_i (y_i - b - z_i beta)^2 + alpha * ||beta||_2^2
```

The default `alpha` is `10.0`. Scikit-learn's deterministic Cholesky solver performs the
fit. Inference reconstructs the dot product from the frozen numeric state rather than
retaining a solver-specific estimator. Optimizer input is:

```text
expected_points_i = max(0, b + z_i beta)
```

The floor exists because the optimizer prediction contract requires non-negative expected
points. Realized labels and residuals may remain negative.

## Chronological fitting and leakage boundary

For decision `(season, gameweek)`:

1. `rows_through` removes all later rows before the projection builder is invoked.
2. Shifted features are built for the current visible history.
3. `rows_before` removes the decision gameweek from the fitted labels.
4. Imputation, standardization, and Ridge coefficients are learned on those historical rows.
5. Deadline-known identity, club, position, and integer price come from the target row.
6. The target outcome is read only after the optimized decision is frozen.

Completed-season feature tables may be cached inside one chronological builder run. The
cache is scoped to that builder and contains only seasons already completed at the decision.
The current season is rebuilt from its visible prefix. This preserves the same feature values
while avoiding repeated reconstruction of immutable history.

Mutation tests cover decision-gameweek outcomes, later outcomes, input row ordering, input
ownership, and repeat-run fingerprints.

## Determinism and provenance

The fitted state records:

- ordered feature names;
- imputation values, centers, scales, coefficients, and intercept;
- training row count;
- training-data SHA-256;
- fitted-model SHA-256.

The training-data digest covers ordered row identity, features, label, model controls, and
feature contract. The model digest covers the exact hexadecimal floating-point state plus
the training digest. `PredictionSnapshot` then fingerprints the model provenance and exact
optimizer projection table. Identical data, configuration, and row content produce identical
model and prediction identities.

## Paired development benchmark

The default benchmark seasons are `2021-22` through `2024-25`. Gameweek 1 is excluded because
it has a different information set. `2025-26` is explicitly rejected by this development
runner as the locked holdout.

Baseline and Ridge use the same ordered fold IDs, form window, cross-season controls,
optimizer configuration, realized outcomes, and scoring policy. Reported prediction metrics
are player-gameweek MAE, RMSE, and mean error overall and by position. Reported decision
metrics include:

- feasibility counts;
- mean realized starting-XI-plus-captain score;
- same-fold Ridge-minus-baseline score differences;
- wins, ties, and losses;
- changed squad, starting XI, and captain counts;
- mean entering-player counts.

The result also returns one learned out-of-sample residual row per player and fold:

```text
fold_id, season, gameweek, player_id, team_id, position,
predicted_points, realized_points, residual
```

where `residual = realized_points - predicted_points`. This table is the explicit Sprint 7
input boundary; scenario code does not need to reconstruct predictions or training splits.

## Artifacts and command

```powershell
.venv\Scripts\python -m scripts.run_learned_benchmark
```

The command uses the pinned local historical archive and writes:

- `artifacts/sprint6/learned_benchmark.json`;
- `artifacts/sprint6/learned_benchmark.md`.

Artifacts are ignored by Git. JSON is machine-readable; Markdown is the review surface.
Both declare that the holdout was not accessed and that no automatic promotion occurred.

The verified `2024-25` smoke run produced 37 feasible paired folds and 26,303 residual rows.
It completed in approximately 596.6 seconds on the development machine. The full four-season
default is consequently a long-running offline benchmark; weekly live inference fits only
the current deadline model and does not replay historical optimizer decisions.

## Integration with the data owner's model

Ridge is not intended to overwrite Ibrahim's feature or model decisions. A production model
integrates by producing exact-aligned `player_id` and `expected_points` values plus a
`PredictionProvenance`. It can then use `prepare_optimizer_projection`, the existing
walk-forward fold builder, evaluator, and the same residual schema. No optimizer change is
required.

If the production model adds fixture, availability, or other fields, ownership and deadline
timing must first be documented in the canonical data contract. Sprint 6 does not fabricate
or infer those inputs.

## Known limitations

- The reference has one fixed `alpha`; it is not tuned.
- Player and team identity are deliberately absent from the feature matrix.
- Fixture strength, availability, transfers, chips, and double-gameweek fixture grain are
  excluded.
- Weekly expanding-window refits prioritize auditable leakage boundaries over speed.
- The four-season default benchmark can run for tens of minutes and currently has no
  checkpoint/resume or progress callback.
- A lower MAE does not guarantee a better optimized squad, so both metric families are shown.
- The locked holdout requires a separately reviewed protocol and is not exposed here.

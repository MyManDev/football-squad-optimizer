# Learned prediction benchmark

Development-only paired comparison; the locked holdout was not accessed.

## Configuration

- Evaluation seasons: `2021-22, 2022-23, 2023-24, 2024-25`
- Model: `squadopt-ridge-reference@ridge-reference-v1`
- Form window: `5`
- Ridge alpha: `10.0`
- Missing values: training median, or zero if a training column is entirely missing
- Negative point predictions: floored at zero

## Player-gameweek prediction metrics

| Model | Observations | MAE | RMSE | Mean error |
| --- | ---: | ---: | ---: | ---: |
| Baseline | 101447 | 1.123725 | 2.233497 | 0.005521 |
| Ridge | 101447 | 1.130040 | 2.099055 | 0.008040 |

## Optimized-decision comparison

- Comparable scored folds: `147`
- Baseline mean realized points: `53.775510204081634`
- Ridge mean realized points: `56.89115646258504`
- Mean paired difference: `3.1156462585034013`
- Ridge win/tie/loss folds: `80/10/57`
- Squad changed folds: `147`
- Starting XI changed folds: `147`
- Captain changed folds: `97`

## Decision

No automatic promotion. This reference must be reviewed and can later be replaced through the same prediction contract by Ibrahim's model.

## Limitations

- The Ridge model is an integration reference, not Ibrahim's production model.
- Opening gameweeks and the locked 2025-26 holdout are not evaluated.
- Fixture, availability, transfer, chip, and multi-gameweek effects are excluded.
- Residual scenarios and scenario-aware optimization are outside Sprint 6.

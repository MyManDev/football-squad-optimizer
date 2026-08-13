# Prepared-Fold Evaluation Specification

## Scope

The Sprint 1 evaluation package measures frozen, single-gameweek squad decisions against
outcomes observed later. It consumes folds prepared by a time-aware data component; it does
not create train/test splits, fit projection models, or inspect historical rows.

The public interface is:

```python
evaluate_prepared_folds(
    folds: Iterable[EvaluationFold],
    config: EvaluationConfig,
) -> EvaluationResult
```

This boundary allows the walk-forward helper tracked by Issue #6 to become a fold producer
without duplicating temporal logic in the optimization layer. The opening-gameweek prior
tracked by Issue #7 is also outside this package.

## Prepared-fold contract

Every `EvaluationFold` contains:

- a unique, non-empty `fold_id`;
- one optimizer-ready projection `DataFrame`;
- a realized-points `DataFrame` for the same decision gameweek;
- optional caller metadata such as season, gameweek, or decision timestamp.

The projection table follows the existing six-column optimizer contract. Realized points
contain at least:

| Column | Contract |
| --- | --- |
| `player_id` | Unique non-null integer or non-empty string; one type per column |
| `total_points` | Finite numeric value; negative scores are allowed |

Fold order is caller-defined and meaningful. It must be chronological before turnover is
interpreted. Fold and run metadata mappings, projection tables, and realized-points tables
are defensively copied when their public models are constructed. The `player_id`
representation must remain integer or text consistently across every fold, and projection
and realized identifiers must use the same representation within a fold. The evaluator
rejects representation drift instead of coercing identifiers and potentially changing
lexical identities such as `007`.

## Scoring policy

The only supported policy is versioned as `realized_squad_points_v1`:

```text
realized_squad_points
    = sum(realized total_points for starting XI)
    + realized total_points for captain
```

The captain term applies the captain's score a second time. Bench points, automatic
substitutions, vice-captain fallback, chips, and platform-specific scoring adjustments are
not modeled. A future policy with different semantics must receive a new versioned name.

Every selected starter and captain must have a realized outcome. Missing outcomes raise
`EvaluationValidationError`; they are not excluded and are never converted to zero. This
fail-closed behavior remains until a versioned missing-outcome policy is approved.

## Fold and summary semantics

`OPTIMAL` and `FEASIBLE` optimizer results are scored. `INFEASIBLE` and solution-free
`UNKNOWN` results remain structured fold results with `realized_squad_points=None`.

The summary reports:

- attempted, feasible, and scored fold counts;
- feasibility rate as feasible folds divided by attempted folds;
- mean realized score and population standard deviation over scored folds;
- mean projected objective value over feasible folds as a diagnostic only;
- median and nearest-rank 95th-percentile solver runtime over attempted folds;
- mean squad turnover over adjacent pairs in which both folds are feasible.

For adjacent feasible squads `S_(t-1)` and `S_t`, turnover is:

```text
|S_t \ S_(t-1)|
```

An infeasible or unknown fold breaks adjacency: no turnover is reported across that gap.
Projected objective values are never treated as realized performance.

## Validation and failure behavior

Prepared-fold validation is strict:

- at least one fold is required;
- fold IDs must be unique;
- outcome columns and player IDs must be complete and unambiguous;
- `total_points` must be finite but may be negative;
- the realized squad score must fit the public finite-float representation;
- every feasible decision must be fully covered by outcomes;
- solver runtime diagnostics must be finite and non-negative.

Schema and outcome errors raise `EvaluationValidationError`. Optimizer validation and solver
errors keep their existing domain exceptions and are not silently converted into scores or
failed-zero responses.

## Reproducibility boundary

`EvaluationConfig` freezes the complete `OptimizationConfig`, the scoring-policy version,
and caller-supplied `run_metadata`. Fold metadata is preserved in every fold result.
Metadata is recursively copied and frozen: mappings remain read-only mappings and sequences
become tuples. Keys must contain non-whitespace text. Values are restricted to nested
mappings and sequences of strings, booleans, integers, finite floats, and null so mutable or
non-portable notebook objects cannot enter the reproducibility record.

The caller remains responsible for providing serializable metadata required by the
experiment contract, including experiment ID, repository commit, dataset version, decision
boundaries, environment versions, and seeds. The evaluator does not read Git state or create
timestamps implicitly because hidden environmental state would make identical inputs
produce different records.

The real-data baseline command records this provenance, the complete fixed optimizer
controls, environment versions, aggregate distributions, and one result row per fold.

## Current limitations

- Walk-forward folds are available, but point-projection model training and calibration
  remain external.
- Player-level uncertainty calibration is implemented by the separate
  `squadopt.uncertainty` package; this evaluator still scores frozen squad decisions only.
- There is no automatic-substitution or bench-order scoring.
- The Sprint 2 DoE is implemented separately; there is no Bayesian Optimization loop or
  experiment storage backend.
- Runtime comparisons still require callers to control and record the execution environment.

# Residual Export Contract

## Purpose

Prediction, recalibration, scenario, and live-risk code must refer to the same out-of-sample
errors. This contract defines the handoff artifact. It does not define a new prediction
model and does not permit in-sample fitted values.

Contract version: `oos_residual_export_v1`.

## Table

Export one CSV or Parquet file per prediction regime. Column order is fixed:

```text
fold_id
season
gameweek
player_id
team_id
position
predicted_points
realized_points
residual
```

Rules:

- one row per `(fold_id, player_id)`;
- `fold_id = <season>-gwNN`;
- `residual = realized_points - predicted_points` within numeric tolerance;
- predicted points are finite and non-negative;
- realized points and residuals are finite and may be negative;
- player IDs use one stable integer-or-string representation in every file;
- team IDs and positions agree between regimes on matched rows;
- all rows are out-of-sample predictions made at the named decision point;
- rows are sorted by season, gameweek, then stable player ID before export;
- the export contains no target/holdout rows that were used to fit the same prediction.

The recalibration CLI adds the regime label from its command-line argument. A file must not
mix two model regimes.

## Manifest

Each table is accompanied by a JSON manifest with these required fields:

```json
{
  "contract_version": "oos_residual_export_v1",
  "candidate_label": "calendar_aware_candidate",
  "model_name": "...",
  "model_version": "...",
  "feature_contract_version": "...",
  "training_contract_version": "...",
  "evaluation_objective": "single_gameweek_realized_squad_points_v1",
  "development_seasons": ["2021-22", "2022-23", "2023-24", "2024-25"],
  "opening_gameweeks_included": false,
  "fold_count": 147,
  "row_count": 101447,
  "repository_commit": "<40-character commit>",
  "dataset_snapshot_id": "<pinned source identity>",
  "table_sha256": "<lowercase SHA-256 of the exact file bytes>",
  "created_at_utc": "<explicit UTC timestamp>"
}
```

`opening_gameweeks_included` is evidence, not a convenience flag. A development export
whose folds begin at GW2 must set it to `false`; it cannot be relabeled as opening evidence.

## Pairing rule

Reference and candidate exports used in one comparison must have identical
`(fold_id, player_id)` keys and identical realized points. Their manifests must name the
same development seasons, evaluation objective, dataset snapshot, and fold policy. The
model and feature identities are expected to differ only where the candidate declaration
permits.

Any mismatch stops the run. Rows are never intersected silently because dropping unmatched
players would change both the prediction-error population and the optimizer decision.

## Live-risk rule

The live-risk command additionally requires the residual model name, version, feature
contract, and a human-readable source ID. These must come from the manifest. For a GW1 live
target, only exports containing historical GW1 out-of-sample folds can produce metrics.
The 147-fold GW2+ development export remains valid for #38 recalibration and invalid for
opening-week live risk.

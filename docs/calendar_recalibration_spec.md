# Calendar-aware residual measurement

## Scope

This contract compares the calendar-blind control residuals with the calendar-aware
production residuals on identical out-of-sample player/fold rows. It is the measurement
boundary required before conformal intervals, player-adaptive scales, or joint scenarios can
be recalibrated. It does not itself claim those later analyses are complete.

The implemented contract version is `calendar_recalibration_measurement_v1`.
The JSON artifact format is independently versioned as `calendar_recalibration_report_v1`,
so serialization changes do not silently redefine the statistical measurement.

## Inputs

Each residual regime carries:

- `fold_id`, `season`, and `gameweek`;
- `player_id`, `team_id`, and `position`;
- `predicted_points`, `realized_points`, and `residual`;
- a `candidate` label identifying the prediction regime.

The two regimes must contain the same `(fold_id, player_id)` keys and agree on season,
gameweek, team, position, and realized points. Residual is verified as
`realized_points - predicted_points`. Inputs are copied and never modified.

Fixture context comes from the versioned fixture snapshot and season-specific team-code
bridge. It is joined by season, gameweek, and team after the fixture table is validated at
fixture grain. Fixture groups are:

- `blank`: no scheduled fixture;
- `single`: exactly one fixture;
- `double_plus`: two or more fixtures.

## Measurements

For the complete matched population and every observed fixture group, the artifact records:

- observation count;
- residual mean;
- population residual standard deviation;
- mean absolute error;
- root mean squared error;
- calendar-aware minus calendar-blind deltas.

Negative MAE or RMSE deltas mean the calendar-aware candidate reduced error. A smaller
standard deviation is not automatically better unless coverage is preserved; coverage is a
later time-aware recalibration measurement rather than an inference made here.

## Reproducibility

The measurement fingerprint hashes the contract, candidate labels, validated residual rows,
and attached fixture groups in canonical order. Each residual regime receives its own content
fingerprint, and the report names the `fixture_snapshot_v1` contract used for the join. JSON
and Markdown reports are deterministic for identical validated inputs.

## Report schema

The JSON artifact has these stable top-level fields:

- `artifact_type`, `report_schema_version`, and `contract_version` identify the artifact;
- `measurement_fingerprint` identifies the complete validated measurement input;
- `configuration` names the reference and candidate regimes;
- `diagnostics` records paired-row/fold counts, fixture-group counts, the fixture contract,
  per-regime residual fingerprints, and explicit recalibration state flags;
- `comparisons` contains one `overall` record plus each observed fixture group, with nested
  reference/candidate metrics and candidate-minus-reference deltas;
- `limitations` carries the claims this measurement is not permitted to make.

Every comparison records `observations`, residual bias, population residual standard
deviation, MAE, and RMSE. JSON serialization rejects non-finite values.

## Explicit non-claims

- Conformal coverage is not measured on the same rows used to calibrate an interval.
- Player-adaptive scales are not declared refitted by this artifact.
- Scenario variance decomposition is not declared refitted by this artifact.
- Gameweek-two-and-later residuals are not used to claim opening-gameweek uncertainty.

Those states remain explicit `false` diagnostics until their time-aware runs are implemented.

## Command

```powershell
python -m scripts.run_calendar_recalibration `
  --reference-residuals artifacts/calendar_blind.csv `
  --candidate-residuals artifacts/calendar_aware.csv `
  --archive-root data/raw/vaastav-fpl `
  --json-output artifacts/calendar_recalibration.json `
  --markdown-output artifacts/calendar_recalibration.md
```

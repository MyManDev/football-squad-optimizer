# In-season blend residual export

Contract: `oos_residual_export_v1`  ·  regime: `in_season_carry_over_blend`
Identity: `squadopt-deterministic-baseline` / `in-season-carry-over-v1`

The live risk layer describes a squad's spread by calibrating on a residual
history, and that description is only honest if the residuals belong to the model
making the decision. From gameweek two that model is
`in-season-carry-over-v1`, and the control export already recorded carries
`form_window_05_v1` -- the archive-fed control, a different model. This is the
matching history for the one that decides.

## What is in it

- **101,447 rows** across **147 folds**, seasons 2021-22, 2022-23, 2023-24, 2024-25.
- One row per `(fold_id, player_id)`; every projection paired with the outcome
  read only after that decision point.
- Residual mean -0.3783, standard deviation 2.2171, range -9.4 to 26.3.

## What it must not be used for

**Opening gameweeks.** Every fold here is gameweek two or later, because the model
needs a played gameweek to read. An opening decision is projected from carry-over
and a price prior instead, and mid-season residuals do not describe that regime --
assuming they do would produce a confident-looking interval with nothing behind
it. The manifest states `opening_gameweeks_included: false` so a consumer can
check rather than assume, and the export refuses to build if an opening gameweek
appears.

That refusal is the same answer the opening-week runbook already gives from the
other side: a gameweek-one risk block is `not_requested`, and that is correct
rather than missing.

## What it does not decide

Nothing on its own. It is an input a live decision may calibrate on once the
wiring exists, not a claim that any interval is well calibrated. Whether these
residuals produce honest coverage is a separate measurement.

The locked holdout was not read: the panel is cut to the development seasons
before anything reads a feature window.

## Manifest

```json
{
  "candidate_label": "in_season_carry_over_blend",
  "contract_version": "oos_residual_export_v1",
  "created_at_utc": "2026-08-28T17:23:53+00:00",
  "dataset_snapshot_id": "8c97b2adb123863c3dd581e730f1360e89815ac2",
  "development_seasons": [
    "2021-22",
    "2022-23",
    "2023-24",
    "2024-25"
  ],
  "evaluation_objective": "single_gameweek_realized_squad_points_v1",
  "feature_contract_version": "in-season-carry-over-features-v1",
  "fold_count": 147,
  "locked_holdout_accessed": false,
  "model_name": "squadopt-deterministic-baseline",
  "model_version": "in-season-carry-over-v1",
  "opening_gameweeks_included": false,
  "predicted_points_decimals": 9,
  "repository_commit": "1f12d46ec345d4fa29c087c1f910ad764445ba27",
  "row_count": 101447,
  "table_sha256": "17f88e6e75618adc01ec6357317a6849bdb053e7eeed1cd6627c8eceab15fc7a",
  "training_contract_version": "in-season-carry-over-v1"
}
```

## Preflight

- Verdict: PASSED (24 checks)
- Table file: `artifacts/residuals/in_season_residuals.csv` (local, not committed)
- Manifest file: `artifacts/residuals/in_season_residuals.manifest.json` (local, not committed)

## Reproduction

```powershell
.venv\Scripts\python -m scripts.export_in_season_residuals
```

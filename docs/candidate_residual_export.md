# Candidate Residual Export

Out-of-sample residuals of the calendar-aware candidate on the chronological development folds, produced from this repository and validated by the artifact preflight. The tables stay local; this document is the committed record.

This is the candidate half of the recalibration pair. The control half is rebuilt by the same command so both manifests name one `repository_commit`.

## Candidate manifest

```json
{
  "candidate_label": "calendar_aware_production",
  "contract_version": "oos_residual_export_v1",
  "created_at_utc": "2026-08-16T11:19:02+00:00",
  "dataset_snapshot_id": "vaastav-fpl@8c97b2adb123863c3dd581e730f1360e89815ac2",
  "development_seasons": [
    "2021-22",
    "2022-23",
    "2023-24",
    "2024-25"
  ],
  "evaluation_objective": "single_gameweek_realized_squad_points_v1",
  "feature_contract_version": "two-stage-appearance-calendar-v1",
  "fold_count": 147,
  "model_name": "squadopt-two-stage",
  "model_version": "two-stage-v1",
  "opening_gameweeks_included": false,
  "repository_commit": "a8f783c782e2f8c2b6690ff7002e38bf1a8fd7b7",
  "row_count": 101447,
  "table_sha256": "c2940348a73cb39f5b65cd7db12656f7ecaae6402857deaaf3ec9dc94be202be",
  "training_contract_version": "expanding_window_opening_price_prior_v1"
}
```

## Candidate preflight

- Verdict: PASSED (31 checks)
- Table file: `C:/Users/ersan/football-squad-optimizer/artifacts/residuals/candidate_residuals.csv` (local, not committed)
- Manifest file: `C:/Users/ersan/football-squad-optimizer/artifacts/residuals/candidate_residuals.manifest.json` (local, not committed)

## Control manifest (rebuilt at this commit)

```json
{
  "candidate_label": "calendar_blind_baseline",
  "contract_version": "oos_residual_export_v1",
  "created_at_utc": "2026-08-16T11:19:02+00:00",
  "dataset_snapshot_id": "vaastav-fpl@8c97b2adb123863c3dd581e730f1360e89815ac2",
  "development_seasons": [
    "2021-22",
    "2022-23",
    "2023-24",
    "2024-25"
  ],
  "evaluation_objective": "single_gameweek_realized_squad_points_v1",
  "feature_contract_version": "form_window_v1",
  "fold_count": 147,
  "model_name": "deterministic_baseline",
  "model_version": "form_window_05_v1",
  "opening_gameweeks_included": false,
  "repository_commit": "a8f783c782e2f8c2b6690ff7002e38bf1a8fd7b7",
  "row_count": 101447,
  "table_sha256": "1ed41f94f245b06d012293a895cdee755a5b1803cb19bcc3795e4a414767a22f",
  "training_contract_version": "deterministic_baseline_no_training_v1"
}
```

## Control preflight

- Verdict: PASSED (31 checks)

## Pair preflight

- Verdict: PASSED (10 checks)
- Reference table: `C:/Users/ersan/football-squad-optimizer/artifacts/residuals/control_residuals.csv` (local, not committed)
- Reference manifest: `C:/Users/ersan/football-squad-optimizer/artifacts/residuals/control_residuals.manifest.json` (local, not committed)

## Reproduction

```powershell
.venv\Scripts\python -m scripts.export_candidate_residuals
```

Recorded at commit `a8f783c782e2f8c2b6690ff7002e38bf1a8fd7b7` on 2026-08-16T11:19:02+00:00.

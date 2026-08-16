# Candidate Residual Export

Out-of-sample residuals of the calendar-aware candidate on the chronological development folds, produced from this repository and validated by the artifact preflight. The tables stay local; this document is the committed record.

This is the candidate half of the recalibration pair. The control half is rebuilt by the same command so both manifests name one `repository_commit`.

## Candidate manifest

```json
{
  "candidate_label": "calendar_aware_learned_rate",
  "contract_version": "oos_residual_export_v1",
  "created_at_utc": "2026-08-16T12:23:48+00:00",
  "dataset_snapshot_id": "vaastav-fpl@8c97b2adb123863c3dd581e730f1360e89815ac2",
  "development_seasons": [
    "2021-22",
    "2022-23",
    "2023-24",
    "2024-25"
  ],
  "evaluation_objective": "single_gameweek_realized_squad_points_v1",
  "feature_contract_version": "learned-rate-calendar-appearance-v1",
  "fold_count": 147,
  "model_name": "squadopt-learned-rate",
  "model_version": "learned-rate-v2",
  "opening_gameweeks_included": false,
  "repository_commit": "8c0ff540a467f417e44d63f47bb0f8d8161ebb29",
  "row_count": 101447,
  "table_sha256": "424b0d76f37bab4ca0c6f6850f8444e95aa660ef69b91a2a8fb017d434fd367f",
  "training_contract_version": "expanding_window_minutes_weighted_ridge_rate_v1"
}
```

## Candidate preflight

- Verdict: PASSED (31 checks)
- Table file: `C:/Users/ersan/football-squad-optimizer/artifacts/residuals/learned_candidate_residuals.csv` (local, not committed)
- Manifest file: `C:/Users/ersan/football-squad-optimizer/artifacts/residuals/learned_candidate_residuals.manifest.json` (local, not committed)

## Control manifest (rebuilt at this commit)

```json
{
  "candidate_label": "calendar_blind_baseline",
  "contract_version": "oos_residual_export_v1",
  "created_at_utc": "2026-08-16T12:23:48+00:00",
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
  "repository_commit": "8c0ff540a467f417e44d63f47bb0f8d8161ebb29",
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

Recorded at commit `8c0ff540a467f417e44d63f47bb0f8d8161ebb29` on 2026-08-16T12:23:48+00:00.

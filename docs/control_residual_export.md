# Control Residual Export

Out-of-sample residuals of the operational control (deterministic baseline) on the chronological development folds, produced from this repository and validated by the artifact preflight. The table stays local; this document is the committed record.

This is control-regime evidence for the uncertainty/scenario/risk layers. It is **not** the #43 candidate export, which remains the prediction side's deliverable.

## Manifest

```json
{
  "candidate_label": "deterministic_baseline_control",
  "contract_version": "oos_residual_export_v1",
  "created_at_utc": "2026-08-15T07:45:27+00:00",
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
  "repository_commit": "6c0b6c43f2503e79b32f194b3d1c30d09a299931",
  "row_count": 101447,
  "table_sha256": "1ed41f94f245b06d012293a895cdee755a5b1803cb19bcc3795e4a414767a22f",
  "training_contract_version": "deterministic_baseline_no_training_v1"
}
```

## Preflight

- Verdict: PASSED (24 checks)
- Table file: `C:/Users/ertug/Desktop/football-squad-optimizer/artifacts/codex-worktrees/control-residual-export/artifacts/residuals/control_residuals.csv` (local, not committed)
- Manifest file: `C:/Users/ertug/Desktop/football-squad-optimizer/artifacts/codex-worktrees/control-residual-export/artifacts/residuals/control_residuals.manifest.json` (local, not committed)

## Reproduction

```powershell
.venv\Scripts\python -m scripts.export_control_residuals
```

Recorded at commit `6c0b6c43f2503e79b32f194b3d1c30d09a299931` on 2026-08-15T07:45:27+00:00.

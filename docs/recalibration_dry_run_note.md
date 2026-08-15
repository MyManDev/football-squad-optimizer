# Recalibration Dry-Run — Framing Note

## What this is

The first end-to-end execution of the preflight-gated time-aware recalibration
pipeline on real data. Both residual exports were produced from this repository at one
commit, validated by the artifact preflight (byte-exact checksums included) inside the
measurement command itself, and compared by the chronological
scale/conformal/evaluation study. The paired artifacts are
`recalibration_dry_run.json` / `recalibration_dry_run.md`.

## What this is not

This is **not** the #38 closeout. #38 compares a calendar-blind reference against the
calendar-aware production candidate, and those residual exports remain the prediction
side's deliverable. The two regimes here are both deterministic-baseline variants:

```text
reference: deterministic_baseline_fw05  (operational control window)
candidate: deterministic_baseline_fw10  (exhaustive-grid optimum window)
```

The run proves the pipeline — handoff gate, pairing rule, fixture bridge,
chronological splits, reporting — with real inputs, so the real #38 artifacts can be
processed without surprises when they arrive.

## Inputs

- Exports: `scripts.export_control_residuals` at one commit, 147 folds / 101,447 rows
  each, identical realized points and fold policy, differing only in
  `model_version` (`form_window_05_v1` vs `form_window_10_v1`) and `candidate_label`.
- Gate: both single-export preflights and the pairing preflight passed inside
  `scripts.run_calendar_recalibration`; a single failed finding would have refused the
  measurement.

## Headline readings (see the paired report for full tables)

- Chronological split: 58 scale-training / 44 conformal / 45 evaluation folds;
  33,103 held-out evaluation rows.
- Held-out conformal coverage is preserved (reference 0.8997 vs candidate 0.8992 at
  the 0.90 target) while the candidate's mean interval width narrows by ~0.36 points
  overall and ~0.38 in double gameweeks.
- Every scenario-decomposition component (common, team, idiosyncratic) shrinks
  slightly under the fw10 regime.

Consistent with the exhaustive grid: the longer form window is not only better in mean
realized squad points, it is also a tighter predictor at unchanged coverage.

## Reproduction

```powershell
.venv\Scripts\python -m scripts.export_control_residuals --form-window 5 `
  --table-name fw05_residuals --summary-output artifacts/residuals/fw05_summary.md
.venv\Scripts\python -m scripts.export_control_residuals --form-window 10 `
  --candidate-label deterministic_baseline_fw10 --table-name fw10_residuals `
  --summary-output artifacts/residuals/fw10_summary.md
.venv\Scripts\python -m scripts.run_calendar_recalibration `
  --reference-residuals artifacts/residuals/fw05_residuals.csv `
  --candidate-residuals artifacts/residuals/fw10_residuals.csv `
  --reference-manifest artifacts/residuals/fw05_residuals.manifest.json `
  --candidate-manifest artifacts/residuals/fw10_residuals.manifest.json `
  --reference-label deterministic_baseline_fw05 `
  --candidate-label deterministic_baseline_fw10 `
  --time-aware `
  --json-output docs/recalibration_dry_run.json `
  --markdown-output docs/recalibration_dry_run.md
```

The residual tables stay local (the repository is not a data store); their manifests'
checksums are recorded in the JSON artifact's preflight provenance.

# Calendar Recalibration Runbook

## Preconditions

- Work from a clean commit containing the prediction implementation being measured.
- Pin the historical archive and record its snapshot/commit identity.
- Freeze the candidate declaration and the benchmark configuration before the formal run.
- Keep the locked holdout absent from development exports.
- Obtain one reference and one candidate artifact satisfying
  `residual_export_contract.md`.

The current 147-fold production-gate residual export starts after opening gameweeks. It can
support the calendar recalibration study but not GW1 live-risk numbers.

## 1. Verify the handoff

For both manifests:

1. verify the file SHA-256;
2. verify model/feature identities and repository commit;
3. verify the same dataset snapshot, seasons, fold count, and objective;
4. verify that neither artifact claims an untouched holdout it has already read;
5. retain the manifests beside the reports.

Do not rename a Ridge or production-candidate residual file as the operational control.

## 2. Run matched residual measurement

```powershell
.venv\Scripts\python -m scripts.run_calendar_recalibration `
  --reference-residuals artifacts/reference_residuals.csv `
  --candidate-residuals artifacts/candidate_residuals.csv `
  --reference-label calendar_blind_control `
  --candidate-label calendar_aware_candidate `
  --archive-root data/raw/vaastav-fpl `
  --json-output artifacts/recalibration/measurement.json `
  --markdown-output artifacts/recalibration/measurement.md
```

Confirm identical paired rows, fixture-contract version, and non-empty fixture groups. The
measurement artifact reports bias/spread/error only; it makes no coverage claim.

## 3. Run chronological recalibration

```powershell
.venv\Scripts\python -m scripts.run_calendar_recalibration `
  --reference-residuals artifacts/reference_residuals.csv `
  --candidate-residuals artifacts/candidate_residuals.csv `
  --reference-label calendar_blind_control `
  --candidate-label calendar_aware_candidate `
  --archive-root data/raw/vaastav-fpl `
  --time-aware `
  --scale-training-fraction 0.40 `
  --conformal-calibration-fraction 0.30 `
  --confidence-level 0.90 `
  --json-output artifacts/recalibration/time_aware.json `
  --markdown-output artifacts/recalibration/time_aware.md
```

Review:

- scale, conformal, and evaluation fold IDs are disjoint and chronological;
- coverage and width overall and by blank/single/double-plus group;
- player-scale deltas for players with DGW history;
- common/team/idiosyncratic component spread deltas;
- zero refitting on the evaluation slice;
- measurement/configuration/study fingerprints.

Small fixture groups are reported as small; they are not padded, merged, or declared
conclusive.

## 4. Decide what the result permits

The study permits updating uncertainty/scenario calibration evidence. It does not promote a
prediction model, change the operational control, or change the optimizer. The #43 candidate
still passes or fails its own frozen single-gameweek gate.

For live GW1 risk, inspect `opening_gameweeks_included` in the control manifest. If false,
the correct state is structured `unavailable`. Do not point the live command at the
candidate residual export and do not reuse GW2+ residuals.

## 5. Quality checks

```powershell
.venv\Scripts\python -m pytest
.venv\Scripts\ruff check .
.venv\Scripts\ruff format --check .
.venv\Scripts\mypy --strict src
```

Archive the commands, environment versions, manifests, JSON/Markdown outputs, and git commit
together. Reports without their residual manifests cannot support a reproducibility claim.

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

Run the artifact preflight (`artifact_preflight_spec.md`) against both exports and their
pairing, asserting the agreed population:

```powershell
.venv\Scripts\python -m scripts.run_artifact_preflight `
  --table artifacts/candidate_residuals.csv `
  --manifest artifacts/candidate_residuals.manifest.json `
  --reference-table artifacts/reference_residuals.csv `
  --reference-manifest artifacts/reference_residuals.manifest.json `
  --expect-fold-count 147 `
  --expect-row-count 101447 `
  --expect-seasons 2021-22,2022-23,2023-24,2024-25 `
  --json-output artifacts/recalibration/preflight.json
```

The preflight covers the file SHA-256, model/feature identities, repository commit, dataset
snapshot, seasons, fold/row populations, the opening-gameweek evidence flag, and the pairing
rule (identical keys, identical realized points, no silent intersection). Retain the JSON
record and the manifests beside the reports.

Do not rename a Ridge or production-candidate residual file as the operational control.

## 2. Run matched residual measurement

```powershell
.venv\Scripts\python -m scripts.run_calendar_recalibration `
  --reference-residuals artifacts/reference_residuals.csv `
  --candidate-residuals artifacts/candidate_residuals.csv `
  --reference-manifest artifacts/reference_residuals.manifest.json `
  --candidate-manifest artifacts/candidate_residuals.manifest.json `
  --reference-label calendar_blind_control `
  --candidate-label calendar_aware_candidate `
  --archive-root data/raw/vaastav-fpl `
  --json-output artifacts/recalibration/measurement.json `
  --markdown-output artifacts/recalibration/measurement.md
```

With the manifest arguments present, the command re-runs the preflight itself and refuses to
measure anything if a single finding fails, so a formal measurement cannot be produced from
an artifact that violates its contract.

Confirm identical paired rows, fixture-contract version, and non-empty fixture groups. The
measurement artifact reports bias/spread/error only; it makes no coverage claim.

## 3. Run chronological recalibration

```powershell
.venv\Scripts\python -m scripts.run_calendar_recalibration `
  --reference-residuals artifacts/reference_residuals.csv `
  --candidate-residuals artifacts/candidate_residuals.csv `
  --reference-manifest artifacts/reference_residuals.manifest.json `
  --candidate-manifest artifacts/candidate_residuals.manifest.json `
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

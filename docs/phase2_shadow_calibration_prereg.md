# Pre-registration: Phase 2 shadow calibration — the deciding model's own spread, measured internally

Written **2026-08-28, before any Phase 2 shadow measurement exists or runs**. The gates
below are fixed here so they cannot drift toward the numbers once they arrive. Nothing
in this document changes what members see: **no outcome of any measurement under this
protocol publishes a probability, percentage, quantile, interval or spread to member
advice or to the site** — the honesty envelope (`PUBLISHABLE_FIELDS`,
`FORBIDDEN_FIELD_PATTERN`) stays closed regardless of every result.

## Which side of the closed line this is

Three pre-registered constructions of windowed crowd-relative probabilities failed as
declared (`rival_calibration`, `anchored_calibration`, `overlap_calibration`) and the
line's own stop-rule binds: those probabilities are not honestly claimable from this
scenario model, and re-attempting them requires a changed scenario model and a new
pre-registration naming it. **This protocol does not reopen that line.** It calibrates
the *own-side* quantities the stop-rule never touched:

1. **Player expected-points intervals** for the model that actually decides live from
   gameweek 2 — `in-season-carry-over-v1` — whose residual export exists
   (`docs/in_season_residual_export.md`) but is explicitly "an input, not a
   calibration claim". Every fitted calibration committed so far wraps the archive-fed
   control (`form_window_05_v1`); none wraps the deciding model.
2. **Squad-level distribution honesty** (PIT / tail rates) for the same model, via the
   existing scenario-audit instrument.

Rank / league-position probability is out of scope (no ground truth exists — the
archive has no mini-league). Multi-week (h>1) aggregation is out of scope and may not
ride out through this protocol; it requires its own pre-registration.

## Population and split

- **Eligible development seasons**: 2021-22, 2022-23, 2023-24, 2024-25.
- **Fit/evaluation split** (the committed control-record pattern): fit on
  2021-22..2023-24, evaluate frozen on 2024-25 — no refit after any evaluation number
  is visible.
- **Walk-forward discipline**: residual history visible to a fit is strictly earlier
  than every evaluated fold (`validate_residual_history` ordering); opening gameweeks
  (gameweek ≤ 1) are refused, never inferred from GW2+ residuals.
- **Live-season shadow loop** (2026-27): each settled gameweek may be shadow-scored
  only with a calibration fit on strictly earlier folds. The live loop **abstains** —
  it makes no claim — before **8 settled gameweeks** exist (the
  `min_history_folds` precedent).

## Forbidden holdout

The locked 2025-26 season is **never read** — a no-read protocol, not a no-influence
protocol. Any loader invoked under this protocol receives an explicit season list;
artifact provenance records the actually loaded seasons; `holdout_untouched` is
derived from the loaded data, never written as a literal; and a run whose loaded data
contains 2025-26 aborts without writing artifacts (the boundary pattern fixed in the
strategy bench's post-run amendment).

## Residual provenance, bound

A shadow calibration is conditional on the model it wraps
(`issue38_calibration_decision.md`): it must name **one** `oos_residual_export_v1`
export — label, model identity, `table_sha256` — and that manifest must be **committed
to the repository before the measurement runs**. Calibrating one model's spread on
another model's residuals is refused (the #45 rule; `live/risk.py`'s
`MODEL_MISMATCH` is the enforcement precedent). Declared prerequisite, recorded here
so satisfying it is not tuning: the in-season export currently has **no committed
manifest** — it must be regenerated, pass `run_artifact_preflight`, and have its
fingerprint block committed before the first binding run.

## Metrics and gates, fixed before any number

Horizon: **h=1 only**, per fold, on the frozen evaluation season.

- **Gate P1 (player coverage)**: empirical coverage of the 0.90 interval satisfies
  |coverage − 0.90| ≤ 0.03 pooled, and ≤ 0.05 within each fixture group
  (`single`, `double_plus`) that carries ≥ 200 player-gameweek rows; a thinner group
  is reported, not gated. Mean width is reported as a finding, never gated.
- **Gate S1 (squad PIT location)**: mean PIT over evaluation folds lies in
  [0.43, 0.57].
- **Gate S2 (squad lower tail)**: the realized-below-q10 rate over evaluation folds
  lies in [0.04, 0.16].
- Blank fixtures are represented zeros by construction and sit outside every
  calibration cell; they are never imputed.

**Resampling unit**: development population — fold-level bootstrap, 5000 resamples,
90% intervals; live-season weekly series — season-aware moving block bootstrap, block
length 4 (`PromotionPolicy` defaults, as in the strategy bench). **Seeds, in-doc**:
bootstrap seed **0**; scenario draws seed **11** (the rival-line precedent); both are
recorded in the artifact and may not move.

**Minimum sample**: no gated claim from fewer than **30 evaluation folds**
(development) or **8 settled gameweeks** (live loop). Below the floor the outcome is
**ABSTAINED**, which is distinct from FAILED.

## Outcomes and their consequences

- **Pass (all gates)** unlocks exactly one thing: `shadow_status:
  calibrated_internal` in the internal shadow report. No member-facing surface, no
  published field, no contract, and no strategy evidence status changes on a pass.
- **Fail (any gate)** is a valid, recorded result: the negative is committed, the
  thresholds do not move, and there is no retry, re-tune or reinterpretation without
  a new pre-registration.
- **Abstain** (insufficient sample, missing or mismatched manifest, opening gameweek,
  unprovable inputs) is reported with its reasons — never silently skipped, never
  converted to a pass or a fail.
- **Missing data is never zero**: a fold with a missing outcome fails closed
  (`evaluation_spec` rule); a row the capture cannot prove abstains from its cell.

## Public-output prohibition

Shadow artifacts are internal measurement records: they live in `docs/` (committed)
or `data/` (local, gitignored), **never under `web/public`**; the shadow report
contract (`shadow_calibration_report_v1`) is not referenced by `ui_view_v1` or any
site payload; and guard tests sweep the published league tree for probability-shaped
keys and text in both languages. Every committed measurement artifact under this
protocol carries its `docs/measurements_index.md` row.

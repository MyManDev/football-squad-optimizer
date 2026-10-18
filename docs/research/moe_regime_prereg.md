# Regime-gated experts for the Phase C components: pre-registration

Line 3 (`regime`) of the mixture-of-experts programme, declared on 2026-10-17 before any
candidate code was written. Nothing in this note changes after the result is read. It
promotes nothing: the candidate is a declared, non-default estimator option, and a pin is
a separate reviewed change made after the record is read.

## The idea

The served Phase C components (`phase_c_control_components_v1`) fit one estimator set on
every training row: a standardized logistic regression for appearance and two ridge
regressions for minutes and points given an appearance, on the
`phase_c_component_form_window_v1` features. The candidate fits one such expert set per
declared regime and mixes the experts' outputs with a soft gate, so a double gameweek is
not scored by coefficients learned mostly on single gameweeks, and a row under the
defensive-contribution scoring era is not scored by coefficients learned mostly before it.

## The regimes, declared

A training or scoring row carries exactly one regime label, the cross of two indicators:

- **Fixture regime** of the row's gameweek: `single` (`fixture_count == 1`) or `double`
  (`fixture_count >= 2`). `blank` (`fixture_count == 0`) is the contract's zero: the
  served components already answer zeros for a blank gameweek before any estimator is
  read, and no row of the five-season development table carries a blank fixture count
  (the exported control table holds fixture counts of 1 and 2 only). A blank row, if one
  ever appeared, would enter no expert fit and no gate fit.
- **Rule era** of the row's season: `pre_defcon` (2021-22 to 2024-25) or `defcon`
  (2025-26 onward, the defensive-contribution and keeper rules). The era is a function
  of the season label: start year 2025 or later is `defcon`. This is the same boundary the
  v2 export's `rule_era` manifest block records.

The four labels are `single_pre_defcon`, `double_pre_defcon`, `single_defcon` and
`double_defcon`.

- **Season age** is the third declared regime term: `target season start year minus the
  row's season start year`. It is an input of the gate, not a label and not a sample
  weight; every scoring row has age 0 by construction, and training rows of earlier
  seasons have age 1, 2, 3 or 4.

## The experts, declared

For each regime label present among the fold's usable training rows, the served pair with
the control's constants, fitted on that regime's rows only and nothing else:
`StandardScaler` + `LogisticRegression(C=1.0, solver="lbfgs", max_iter=1000)` for
appearance on the regime's complete-feature rows; `StandardScaler` +
`Ridge(alpha=1.0, solver="cholesky")` for minutes and for points on the regime's appeared
rows with both conditional targets. Equal weighting of rows inside every expert.

An expert set exists for a regime only when that regime has at least
`minimum_training_rows` (200, the control's constant) complete-feature rows with both
appearance outcomes present and at least 200 conditional rows. A regime below that is
absent for the fold: the gate's mass on it is dropped and the remaining mass is
renormalized over the present experts. The control's own thin-history refusals are applied
first and unchanged; a fold in which no regime expert can be fitted is refused the way the
control refuses a thin fold, and the refusal is counted in the manifest.

The data say where the thin regimes lie, and this is recorded before the run so the reading
cannot be surprised by it: double-gameweek rows are 2,217 / 1,548 / 983 / 364 / 409 of the
five seasons' scored rows, and double gameweeks of 2025-26 are gameweeks 26, 33 and 36, so
`double_defcon` can exist only late in 2025-26 and `single_defcon` only from about
2025-26 gameweek 3. Early 2025-26 folds are therefore scored by the `pre_defcon` experts
routed by fixture count.

## The gate, declared

`StandardScaler` + `LogisticRegression(C=1.0, solver="lbfgs", max_iter=1000,
random_state=0)` over the regime labels present among the fold's usable training rows
(multinomial under lbfgs; a fold whose usable rows carry one label gets a constant gate).
Its inputs are the eight v1 feature columns plus the three regime terms: the `double`
indicator, the `defcon` indicator and the season age, standardized with the rest. It is
fitted on every usable training row of the fold, including rows of regimes whose expert is
absent. At scoring the gate reads the scoring row's own indicators and age 0.

The mixed prediction of each component is the gate-weighted mean of the present experts'
outputs: appearance probability, conditional minutes and raw conditional points. The
control's bounds are applied after mixing, exactly where the control applies them:
appearance in [0, 1], minutes in [0, 90 x fixtures], public points at or above zero,
`control_expected_points` equal to appearance times points.

No constant above is searched; every one is the control's own or a declared indicator. If
anything here has to change before the run, a dated note is added below and committed
before the run.

## How this differs from the season-weighting arm

`phase_c_components_season_half_life_v1` (record `phase_c_v2_development_method.md`)
kept one estimator set and multiplied every training row's weight by `0.5 ** season age`,
so older rows informed the single fit less; it lost on the points rule. This arm keeps
every row at weight one inside its expert, fits separate expert sets by fixture regime and
rule era rather than one reweighted set, and lets the season-age term enter only the gate
as an input. No row of any season is down-weighted in any expert fit.

## Implementation, declared

`ComponentModelConfig(estimator="regime")` in `src/squadopt/prediction/component_models.py`,
a fourth value beside `linear`, `gradient_boosting` and `gradient_boosting_points`, model
version `phase_c_control_components_regime_v1`, equal weighting only (the arm refuses
season-age weighting). `scripts/export_component_oof.py --development-scope v2
--season-weighting equal --estimator regime` writes
`phase_c_component_oof_development_v2_equal_regime`;
`scripts/compare_component_oof_development.py --candidate-arm regime` compares it. The fit
takes the fold's target season to compute the season-age term; the export passes the
decision's season. The scoring frame must carry its `season` column for this estimator.
Nothing served reads the option.

## The measurements

Chronological folds only; every fit uses rows strictly before the target gameweek. The
Phase C v2 development scope reads 2025-26 as development data, never as an unseen holdout;
every manifest and the record say so.

1. **The v2 points-MAE rule, 184 folds.** Control: the linear equal-weight arm exported at
   the same commit. The rule of the v2 method, unchanged: the candidate is preferred only
   if (i) its 2025-26 points MAE is lower than the control's, (ii) the 90% season-aware
   moving-block interval of the per-fold paired differences (control MAE minus candidate
   MAE) on 2025-26 lies entirely above zero, and (iii) the same interval on 2024-25 does
   not lie entirely below zero. Appearance log loss and Brier and minutes MAE are reported
   beside the rule and do not enter it.
2. **The 147 decision folds.** The candidate exported at the same commit for 2021-22 to
   2024-25 and run through `scripts/evaluate_phase_c_components.py --development-contract
   phase_c_component_oof_development_v2` (squads solved from the arm's expected points,
   official autosub and captain scoring, the frozen ridge control on the same folds).
   Paired on the same folds against the linear components' reading recorded beside the
   gradient-boosting comparison (table sha256 `d8827053...`, mean 63.4150, +4.8912 against
   the ridge control): candidate minus linear, mean, median, the 90% interval, wins / ties
   / losses and the per-season means.

Intervals come from `squadopt.evaluation.statistics.season_aware_moving_block_interval`
with `PromotionPolicy(confidence_level=0.90, bootstrap_resamples=5000,
moving_block_length=4, deterministic_seed=0)`. Seed 0 everywhere; the fits are
deterministic given the rows.

## The gate (clauses, thresholds)

| clause | passes when |
| --- | --- |
| R1 | 2025-26 points MAE, candidate below control |
| R2 | 2025-26 paired interval (control minus candidate) entirely above zero |
| R3 | 2024-25 paired interval not entirely below zero |
| D1 | decision-level paired mean, candidate minus linear, at or above zero on the 147 folds |

The line is proposed for a pin only if R1, R2, R3 and D1 all pass. D1 passing with an
interval across zero is recorded as such and left to the owner's call. A fail is recorded
exactly like a pass. No scenario distribution changes, so S1 and S2 are not measured.

## Budget

One export of the control (184 folds) and one of the candidate at the run commit, one
comparison, one four-season export of the candidate and one decision evaluation. No rerun
after a result is read; no constant changed after a result is read. Outputs under
`C:/Users/ertug/AppData/Local/Temp/moe3/`.

## Not measured here

- The gate's regularization, the expert constants and the minimum-rows guard at any value
  but the declared one.
- Experts fitted on gate-weighted rows (EM) rather than on their regime's rows.
- The v2 feature contract, the boosted estimators and the appearance-power probes as
  experts.
- S1 and S2: the arm changes expected points only, not a scenario sampler.
- Per-regime error breakdowns are reported as diagnostics; they gate nothing.

## Machine

Windows 11 (10.0.26200), Intel64 Family 6 Model 183, Python 3.13.5, numpy 2.5.2, pandas
3.0.5, scipy 1.18.0, scikit-learn 1.9.0, ortools 9.15.6755. Three other lines of the
programme run on the same machine at the same time, so wall-clock timings are not part of
the record.

## Record

`docs/research/moe_regime.json` and `docs/research/moe_regime.md`, every number in the md
reproducible from the json, plus a row in `docs/measurements_index.md` and one in
`docs/research/README.md`.

# Mixture-of-experts line 1, `mixture`: pre-registration

This note declares the gated-mixture candidate of the Phase C conditional components and the
three readings it is measured by. It is written before any candidate code and before the
measurement, and it is not changed by the result; a change forced before the run is added as
a dated note below and committed before the run. It changes nothing in the frozen Phase C v1
contract, its artifacts or its evaluation protocol, and it promotes nothing: a pin is a
separate reviewed change made by the owner after reading the record. Written 2026-10-17.

## What the candidate is

The served components predict three things per player and gameweek: the appearance
probability (a logistic regression), the expected minutes given an appearance and the expected
points given an appearance (two ridge regressions), all on the nine
`phase_c_component_form_window_v1` features. The two conditional estimators are single-mean
models of targets that are not single-peaked: minutes given an appearance sit near a full
match or near a short cameo, and points given an appearance sit at the one or two appearance
points or well above them when the player returns.

The candidate replaces each conditional ridge by a gated mixture of two ridge experts and
keeps everything else: the appearance estimator stays the served logistic regression (the zero
atom stays where it is), the rows, features, targets, folds, routes and bounds stay the
control's. The candidate is `ComponentModelConfig(estimator="mixture")`, model version
`phase_c_control_components_mixture_v1`, the fourth estimator option beside `linear`,
`gradient_boosting` and `gradient_boosting_points`. It refuses season-age weighting and is
fitted under equal row weights only.

### Regimes (the supervised gate labels)

Both regime rules read the realized conditional targets of the training rows and nothing else;
they are constants, not searched.

- **Minutes given an appearance.** Expert `full` is fitted on rows with
  `minutes_target >= 60 * fixture_count` (at least the 60-minute appearance threshold of the
  scoring rules per fixture of the gameweek), expert `short` on the other appeared rows.
- **Points given an appearance.** Expert `return` is fitted on rows with
  `points_target >= 4` (the two points of a full appearance plus at least two more: a clean
  sheet, a goal, an assist or bonus), expert `no return` on the other appeared rows.

### Gate and experts

- **Gate:** `StandardScaler` + `LogisticRegression(C=1.0, solver="lbfgs", max_iter=1000,
  random_state=0)` on the nine v1 features, fitted on all appeared training rows with the
  regime label as the target; the same estimator and constants as the served appearance
  model. One gate per conditional component (one for minutes, one for points).
- **Experts:** `StandardScaler` + `Ridge(alpha=1.0, solver="cholesky")` on the same nine
  features, one fitted on each regime's rows only, every row weighing 1.
- **Expected value:** the gate-weighted mean,
  `g(x) * expert_high(x) + (1 - g(x)) * expert_low(x)` with `g` the gate's probability of
  the `full` or `return` regime; then the control's own bounds (minutes clipped to
  `[0, 90 * fixture_count]`, public points at or above zero, `control_expected_points` equal
  to the appearance probability times the conditional points).
- **Predictive distribution:** the gated mixture of the experts' residual distributions,
  `g(x) N(expert_high(x), s_high^2) + (1 - g(x)) N(expert_low(x), s_low^2)`, where each
  `s` is the standard deviation (`ddof=1`) of that expert's residuals on its own training
  rows, floored at 1.0 minute for minutes and 0.5 points for points. The control's
  predictive distribution, the comparator for the proper-scoring reading, is the single
  Gaussian `N(ridge(x), s^2)` with `s` the ridge's residual standard deviation on all
  appeared training rows under the same floors.
- **Thin regimes:** a fold is fitted only if both regime labels are present and each regime
  has at least `max(2, minimum_training_rows // 4)` rows (50 at the declared default of
  200). Otherwise the fit is refused like thin history: the fold's rows take the
  `direct_control` route and the manifest records the refusal.
- **Seeds:** `random_state=0` everywhere; the fit is deterministic given the rows.

### The distribution output

Every v2 development export (control and candidate alike) writes a sidecar beside its table,
`<table>.distribution.csv`, one row per `component_model` row of a fitted fold, keyed by
`season`, `target_gameweek`, `fold_id` and `player_id`, with the columns
`distribution_family`, `minutes_gate`, `minutes_mean_low`, `minutes_mean_high`,
`minutes_scale_low`, `minutes_scale_high`, `points_gate`, `points_mean_low`,
`points_mean_high`, `points_scale_low` and `points_scale_high`. The gate is the weight of
the high expert (`full`, `return`). The control writes `gaussian_1` with gate 0, the
single Gaussian in the low slots and the high slots missing; the candidate writes
`gaussian_mixture_2`. The sidecar's path, digest, columns and family are recorded in the
manifest's `estimator` block under `distribution_sidecar`. The out-of-fold table and its
column contract are unchanged, so the development reader and the decision evaluation read
the candidate exactly as they read the control; the sampler line reads the sidecar.

## The three readings

All three are run from one commit of a clean tree, with the repository venv (pandas 3,
scikit-learn 1.9), the archive at `data/raw/vaastav-fpl`, and the outputs under
`C:/Users/ertug/AppData/Local/Temp/moe1/`. 2025-26 is read under the Phase C v2 development
scope as development data, never as an unseen holdout; every manifest and the record say so.

### (a) The v2 points-MAE rule, 184 folds

`scripts.export_component_oof --development-scope v2 --season-weighting equal` writes the
control table `phase_c_component_oof_development_v2_equal`; adding `--estimator mixture`
writes `phase_c_component_oof_development_v2_equal_mixture`. Both from the same commit.
`scripts.compare_component_oof_development --candidate-arm mixture` applies the v2 rule
unchanged; its three clauses are **the gate of this line**:

1. the candidate's 2025-26 points MAE is lower than the control's;
2. the 90% season-aware moving-block interval of the per-fold paired differences (control
   MAE minus candidate MAE) on 2025-26 lies entirely above zero;
3. the same interval on 2024-25 does not lie entirely below zero.

Intervals from `squadopt.evaluation.statistics.season_aware_moving_block_interval` under
`PromotionPolicy(confidence_level=0.90, bootstrap_resamples=5000, moving_block_length=4,
deterministic_seed=0)`. Appearance Brier and log loss and minutes MAE are reported beside the
rule and do not enter it; the appearance metrics are expected to equal the control's to
rounding, since that estimator is shared.

### (b) Proper scoring of the predictive distribution, reported beside the rule

`scripts.score_component_distribution --artifact-dir <dir> --candidate-arm mixture` reads
both arms through the development reader, checks they are one paired measurement, joins the
two sidecars on the key, and scores every row that appeared (`appearance_target == 1`) and
is on the `component_model` route in both arms. Points are integers, so both arms are scored
as discretised distributions:

- **log score** `log(F(y + 0.5) - F(y - 0.5))` with `F` the arm's predictive CDF, the
  probability floored at 1e-12; higher is better;
- **PIT** the mid-point `(F(y - 0.5) + F(y + 0.5)) / 2`; a calibrated distribution has mean
  PIT near 0.5, a lower-tail rate (PIT below 0.05) near 0.05 and an upper-tail rate (PIT at
  or above 0.95) near 0.05.

Reported per season and pooled for points and for minutes: mean log score, mean PIT, the two
tail rates, and the number of rows. The paired statistic is the per-fold mean log score of the
candidate minus the control's, summarised with the same interval helper and policy on
2025-26 and on 2024-25, with wins, ties and losses by fold. The declared reading: the
candidate's distribution is **sharper** if the 2025-26 interval lies above zero and the
2024-25 interval does not lie below zero; **worse** if the 2025-26 interval lies below zero;
**undecided** otherwise. This reading is recorded beside the rule and is not a gate clause.

### (c) The 147 decision folds

The candidate is exported at the same commit for the frozen decision seasons 2021-22 to
2024-25 (`--seasons 2021-22,2022-23,2023-24,2024-25`) and run through
`scripts.evaluate_phase_c_components --development-contract phase_c_component_oof_development_v2`
(147 folds, squads solved from the arm's expected points, official autosub and captain
scoring, the frozen ridge control on the same folds). Its per-fold realized squad points are
paired against the linear components' reading recorded beside the gradient-boosting
comparison (`scratchpad/phase_c_v2_decision/decision_control.json`, 147 folds, mean +4.8912
against the ridge control). Reported: the mean and median paired difference, the 90% interval
from the same helper and policy, wins, ties and losses, and the per-season means.

## The pin condition

A pin is proposed only if the gate (a) passes and the paired decision-level mean of (c) is
not negative. A positive mean whose interval crosses zero is recorded as such and left to the
owner's call. Nothing about scenario distributions changes in this line (the samplers are not
touched), so S1 and S2 are not run here. A failing result is recorded exactly like a passing
one.

## Budget

One export per arm per scope (two five-season tables, one four-season candidate table), one
comparison, one scoring run, one decision evaluation. No threshold, constant, regime rule or
feature is retried after a number is seen.

## What is not measured

- No other regime threshold, gate estimator, expert count or regularisation strength.
- No change to the appearance estimator, the features, the targets, the routes or the bounds.
- No sampler, no S1/S2 run, no scenario-level reading: the sidecar is an output for the
  sampler line, not a measurement here.
- Season-age weighting with the candidate (refused by the fit).
- The v1 contract, which refuses the candidate as it refuses the boosted arms.

## Record

`docs/research/moe_mixture.json` and `docs/research/moe_mixture.md`, every number of the
md reproducible from the json; the comparison report, the scoring report, the decision-level
reading and the arm manifests inside the json; an index row in `docs/measurements_index.md`
and a row in `docs/research/README.md`.

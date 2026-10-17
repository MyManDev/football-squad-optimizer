# Regime-gated experts for the Phase C components: the out-of-fold comparison and the decision-level reading

Record of the measurement declared in [moe_regime_prereg.md](moe_regime_prereg.md) (mixture-of-experts line 3). JSON twin: `moe_regime.json`. Both arms were exported at commit `1ec7ae20` from a clean tree under the Phase C v2 development scope (2021-22 to 2025-26, 184 walk-forward folds, 130,095 rows, 128,627 on the component route) and compared by `scripts.compare_component_oof_development --candidate-arm regime` on 2026-10-17T16:37:55Z. 2025-26 was read as development data, as the scope declares; the locked holdout was not spent. Nothing here promotes anything: promotion is a separate reviewed change.

**Verdict under the pre-declared rule: `no_selection`.** Primary season 2025-26: control points MAE 1.00578, candidate 1.01793, mean paired fold difference -0.01222 with the 90% season-aware moving-block interval [-0.01619, -0.00805] (37 paired folds), which lies below zero. Control-era season 2024-25: 1.02523 against 1.02682, interval [-0.00279, -0.00009], which lies below zero.

## The gate clauses

| clause | value | result |
| --- | --- | --- |
| R1, 2025-26 points MAE below the control | 1.01793 against 1.00578 | fail |
| R2, 2025-26 paired interval above zero | [-0.01619, -0.00805] | fail |
| R3, 2024-25 paired interval not below zero | [-0.00279, -0.00009] | fail |
| D1, decision-level paired mean at or above zero | +0.5442 [-0.626, +1.667] | pass |

## The three components, pooled and per season (control / candidate)

| season | appearance log loss | candidate | minutes MAE | candidate | points MAE | candidate |
| --- | --- | --- | --- | --- | --- | --- |
| pooled | 0.34623 | 0.34640 | 16.1605 | 16.1041 | 1.07155 | 1.07286 |
| 2021-22 | 0.38735 | 0.38767 | 19.8276 | 19.6847 | 1.25596 | 1.24715 |
| 2022-23 | 0.35005 | 0.35007 | 16.8703 | 16.9167 | 1.11731 | 1.11570 |
| 2023-24 | 0.33881 | 0.33880 | 15.1531 | 15.2567 | 0.99740 | 0.99788 |
| 2024-25 | 0.34594 | 0.34602 | 15.4857 | 15.6347 | 1.02523 | 1.02682 |
| 2025-26 | 0.31886 | 0.31928 | 14.3393 | 13.9176 | 1.00578 | 1.01793 |

Lower is better in every column. Pooled points MAE 1.07155 to 1.07286.

By fixture regime, pooled over the five seasons (control / candidate, points MAE, then appearance log loss):

| fixture group | rows | points MAE | candidate | appearance log loss | candidate |
| --- | --- | --- | --- | --- | --- |
| double_plus | 5,473 | 1.84013 | 1.74084 | 0.33658 | 0.33502 |
| single | 123,154 | 1.03740 | 1.04318 | 0.34666 | 0.34690 |

Where the experts existed, read from the exported control table (first fold with at least 200 complete rows and 200 appeared rows of the regime strictly before it; a diagnostic, not a gate): `single_pre_defcon` from 2021-22-gw04, `double_pre_defcon` from 2021-22-gw27, `single_defcon` from 2025-26-gw03. Before those folds the gate's mass on the absent regime was renormalized over the present experts.

## Decision-level reading (declared with the rule)

The candidate was exported at the same commit for the frozen decision seasons 2021-22 to 2024-25 and run through the repository's decision comparison (`scripts.evaluate_phase_c_components --development-contract phase_c_component_oof_development_v2`): 147 folds, squads solved from the arm's expected points and scored under the official autosub and captain rules, against the frozen ridge control on the same folds. The linear components' row is the reading recorded beside the gradient-boosting comparison.

| arm | mean realized squad points | against the ridge control | wins / ties / losses | zero-minute starters | autosub points |
| --- | --- | --- | --- | --- | --- |
| linear components | 63.4150 | +4.8912 | 83 / 8 / 56 | 83 | 230 |
| regime-gated experts | 63.9592 | +5.4354 | 86 / 8 / 53 | 82 | 228 |

Paired on the same folds, candidate minus linear: mean +0.5442 points a gameweek, median +0.0, 90% season-aware moving-block interval [-0.626, +1.667], wins / ties / losses 39 / 86 / 22; by season 2021-22 -1.730, 2022-23 +2.833, 2023-24 +1.108, 2024-25 +0.027.

## What this says

The rule does not prefer the candidate; the linear control stays in place and the decision-level reading is recorded beside it as a finding.

The gate is close to hard where a regime is well populated, so the candidate is in effect
separate linear fits by fixture regime and rule era. That helps exactly where the pooled fit is
weakest: on double gameweeks the points MAE falls from 1.84013 to 1.74084 and the minutes MAE of
2025-26 falls from 14.3393 to 13.9176. It costs a little everywhere else: single-gameweek rows
(123,154 of the 128,627 scored) are worse by 0.00578, and 2025-26, the primary season of the
rule, is worse by 0.01222 a fold because its `single_defcon` expert is fitted on that season's
own rows alone (from gameweek 3, a few hundred rows at first) while the control reads four
earlier seasons too. The rule weighs every row, so the small loss on the many single rows
outweighs the larger gain on the few double rows and all three rule clauses fail. The decision
level reads the other way: the squads are identical to the linear components' in 86 of the 147
folds, and where they differ the candidate wins 39 to 22, +0.54 a gameweek with an interval
across zero, the gain concentrated in 2022-23 and 2023-24 with 2021-22 against. D1 passes and
R1 to R3 fail, so the pin condition is not met. The one part of this arm with a clean signal, a
separate expert for double gameweeks, is a narrower candidate than the one declared here and
would need its own declaration.

- One paired measurement at each level: the same rows, features, targets, routes, folds and cutoffs; only the estimator differs (one expert set per regime and a gate, against one linear set).
- No scenario distribution changes, so S1 and S2 were not measured.
- The availability rule, the elite-evidence path and the experimental football arm are untouched by this measurement.

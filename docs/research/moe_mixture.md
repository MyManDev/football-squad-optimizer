# Mixture-of-experts line 1, `mixture`: the three readings

Record of the measurement declared in [moe_mixture_prereg.md](moe_mixture_prereg.md). JSON twin: `moe_mixture.json`. Both arms were exported at commit `d186104e` from a clean tree under the Phase C v2 development scope (2021-22 to 2025-26, 184 walk-forward folds, 130,095 rows, 128,627 on the component route) and compared by `scripts.compare_component_oof_development --candidate-arm mixture` on 2026-10-17T16:38:15Z; the distributions were scored by `scripts.score_component_distribution --candidate-arm mixture` on 2026-10-17T16:38:21Z. 2025-26 was read as development data, as the scope declares; the locked holdout was not spent. Machine: Windows-11-10.0.26200-SP0, Python 3.13.5, numpy 2.5.2, pandas 3.0.5, scipy 1.18.0, scikit-learn 1.9.0. Nothing here promotes anything: a pin is a separate reviewed change.

## (a) The v2 points-MAE rule, the gate

**Verdict under the pre-declared rule: `no_selection`.** Clause 1, 2025-26 points MAE lower: control 1.00578, candidate 1.00612, fail. Clause 2, the 2025-26 paired interval above zero: mean paired fold difference -0.00035, 90% season-aware moving-block interval [-0.00119, +0.00045] (37 paired folds), which crosses zero, fail. Clause 3, the 2024-25 interval not below zero: 1.02523 against 1.02723, interval [-0.00295, -0.00093], which lies below zero, fail.

### The three components, pooled and per season (control / candidate)

| season | appearance log loss | candidate | minutes MAE | candidate | points MAE | candidate |
| --- | --- | --- | --- | --- | --- | --- |
| pooled | 0.34623 | 0.34623 | 16.1605 | 16.0384 | 1.07155 | 1.07325 |
| 2021-22 | 0.38735 | 0.38735 | 19.8276 | 19.5851 | 1.25596 | 1.25498 |
| 2022-23 | 0.35005 | 0.35005 | 16.8703 | 16.7048 | 1.11731 | 1.12026 |
| 2023-24 | 0.33881 | 0.33881 | 15.1531 | 15.0290 | 0.99740 | 1.00124 |
| 2024-25 | 0.34594 | 0.34594 | 15.4857 | 15.4054 | 1.02523 | 1.02723 |
| 2025-26 | 0.31886 | 0.31886 | 14.3393 | 14.3105 | 1.00578 | 1.00612 |

Lower is better in every column. The appearance estimator is the control's, so that column agrees to rounding; the conditional minutes and points estimators are the gated mixtures. Pooled points MAE 1.07155 to 1.07325.

## (b) Proper scoring of the predictive distribution, beside the rule

Scored on 52517 rows that appeared and sit on the component route in both arms: the discretised log score `log(F(y + 0.5) - F(y - 0.5))` (higher is better) and the mid-point PIT, the control as its single Gaussian residual and the candidate as its gated two-expert mixture. Points given an appearance, reading `sharper`: per-fold mean log score, candidate minus control, 2025-26 +0.38143 with the 90% interval [+0.35833, +0.40129] (37 / 0 / 0 over 37 folds), 2024-25 +0.50711 [+0.49105, +0.51759] (37 / 0 / 0). Minutes given an appearance, reading `sharper`: per-fold mean log score, candidate minus control, 2025-26 +0.51618 with the 90% interval [+0.50158, +0.54174] (37 / 0 / 0 over 37 folds), 2024-25 +0.49998 [+0.47964, +0.52004] (37 / 0 / 0).

### Points given an appearance

| season | rows | log score (control) | candidate | mean PIT (control) | candidate | lower tail (control) | candidate | upper tail (control) | candidate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| pooled | 52517 | -2.49538 | -2.04345 | 0.4648 | 0.5053 | 0.0041 | 0.0270 | 0.0742 | 0.0411 |
| 2021-22 | 9205 | -2.56593 | -2.14781 | 0.4583 | 0.5020 | 0.0059 | 0.0332 | 0.0809 | 0.0454 |
| 2022-23 | 10456 | -2.48488 | -2.01721 | 0.4613 | 0.4969 | 0.0031 | 0.0278 | 0.0689 | 0.0391 |
| 2023-24 | 10746 | -2.50091 | -2.02075 | 0.4636 | 0.4991 | 0.0044 | 0.0318 | 0.0748 | 0.0426 |
| 2024-25 | 11089 | -2.45201 | -1.94560 | 0.4608 | 0.5005 | 0.0038 | 0.0219 | 0.0686 | 0.0365 |
| 2025-26 | 11021 | -2.48465 | -2.10177 | 0.4785 | 0.5269 | 0.0037 | 0.0214 | 0.0785 | 0.0426 |

### Minutes given an appearance

| season | rows | log score (control) | candidate | mean PIT (control) | candidate | lower tail (control) | candidate | upper tail (control) | candidate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| pooled | 52517 | -4.72526 | -4.18226 | 0.5062 | 0.5105 | 0.0677 | 0.0445 | 0.0331 | 0.0157 |
| 2021-22 | 9205 | -4.82426 | -4.17112 | 0.5097 | 0.5144 | 0.1092 | 0.0665 | 0.0508 | 0.0165 |
| 2022-23 | 10456 | -4.75277 | -4.22106 | 0.4895 | 0.4934 | 0.0681 | 0.0451 | 0.0204 | 0.0114 |
| 2023-24 | 10746 | -4.71242 | -4.17843 | 0.5099 | 0.5131 | 0.0552 | 0.0382 | 0.0317 | 0.0159 |
| 2024-25 | 11089 | -4.67130 | -4.17225 | 0.5090 | 0.5119 | 0.0531 | 0.0350 | 0.0292 | 0.0148 |
| 2025-26 | 11021 | -4.68328 | -4.16857 | 0.5127 | 0.5194 | 0.0593 | 0.0413 | 0.0357 | 0.0196 |

## (c) The 147 decision folds

The candidate was exported at the same commit for the frozen decision seasons 2021-22 to 2024-25 and run through the repository's decision comparison (`scripts.evaluate_phase_c_components --development-contract phase_c_component_oof_development_v2`): 147 folds, squads solved from the arm's expected points and scored under the official autosub and captain rules, against the frozen ridge control on the same folds. The linear components' row is the reading recorded beside the gradient-boosting comparison. The decision tables were exported at `69f18b0c8` (linear) and `d186104eb` (gated mixture). The development-contract admission of the decision scorer was first committed as `b344b9ca7` on `feat/component-decision-development-arm` and merged to `develop` as #1137 (`1079ba64c`, with identical evaluation code) before this record was written; the scorer ran from the `b344b9ca7` checkout on the exported tables, as the earlier gradient-boosting records did.

| arm | mean realized squad points | against the ridge control | wins / ties / losses | zero-minute starters | autosub points |
| --- | --- | --- | --- | --- | --- |
| linear components | 63.4150 | +4.8912 | 83 / 8 / 56 | 83 | 230 |
| gated mixture | 63.0544 | +4.5306 | 82 / 7 / 58 | 83 | 208 |

Paired on the same folds, candidate minus linear: mean -0.3605 points a gameweek, median +0.0, 90% season-aware moving-block interval [-1.068, +0.735] (bootstrap id `phase_c_mixture_vs_linear_decisions`), wins / ties / losses 33 / 78 / 36; by season 2021-22 +0.108, 2022-23 -0.583, 2023-24 +0.486, 2024-25 -1.459.

## Verdict against the pin condition

The gate does not pass; the linear control stays in place and the distribution scoring and the decision-level reading are recorded beside it as findings.

- One paired measurement at each level: the same rows, features, targets, routes, folds and cutoffs; only the conditional estimators differ.
- The availability rule, the elite-evidence path, the samplers and the experimental football arm are untouched by this measurement; S1 and S2 were not run because no scenario distribution changed.

## Record correction

Regenerated on 2026-10-18 at `9c3f072e0` from the same artifacts with a corrected writer; no measured number changed. The JSON twin's decision arms now carry the commit each decision table was exported at (the first writer read a key the decision JSON does not have and wrote null) and the scorer's commit, the paired decision interval carries the bootstrap id and policy it was drawn with, and the scorer note above says the admission had merged to `develop` as #1137 before the record was written (the first version said it was not merged).

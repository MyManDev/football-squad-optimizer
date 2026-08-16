# Measurements Index

One line per committed real-data measurement artifact: what it is, what it found, and
where it came from. Every artifact is recommendation/measurement-only — nothing here
promoted a model, changed the operational control, or read the 2025-26 locked holdout.
Regenerated artifacts must keep passing `scripts.run_measurement_preflight`.

## Deterministic policy

| Artifact | Finding | PR |
| --- | --- | --- |
| `baseline_bayesopt` | First real BO run: best observed `fw10-bw0` at 56.50 mean realized points (147 folds) | #57 |
| `baseline_policy_grid` | Exhaustive 56-cell ground truth; fw10 column holds ranks 1–7; **BO regret 0.0000**, optimum found at iteration 3 | #61 |
| `fw10_screening` + `fw10_frozen_candidate` | Official screening DoE froze `fw10-bw0` as the eligible challenger; holdout plan in `fw10_holdout_plan.md` (run deferred) | #65 |
| `fw10_season_robustness` | Challenger-vs-control delta per development season, in isolation | #74 |
| `selection_optimism` | Winner's curse located: roster residuals unbiased (−0.004), selected starters −2.96, captains −3.86, top-5 ranked −3.53 | #73 |
| `shrinkage_grid` | Does decision-side position-mean shrinkage improve realized squads? (`position_mean_shrinkage_v1`) | #74+ |

## Scenario and risk

| Artifact | Finding | PR |
| --- | --- | --- |
| `scenario_bayesopt` | First 3-factor search; best `fw6-bw0-ra0` at 57.11; risk aversion's mean cost measured | #60 |
| `scenario_bayesopt_deterministic` | Same recommendation under a deterministic work budget (`det=2.0`); trace machine-independent | #64 |
| `risk_frontier` | **Every ra>0 worsens mean AND floor** (q10 −10..−28); premium buys negative protection | #67 |
| `scenario_calibration_audit` | Cause found: +34.5 decision-level location bias; realized scores in the scenarios' extreme lower tail (PIT 0.07) | #68 |
| `scenario_calibration_audit_located_k10/_k2` | Honest negative result: per-player location component does not fix the bias — the curse is selection-time, not player-persistent | #70 |

## Uncertainty and recalibration

| Artifact | Finding | PR |
| --- | --- | --- |
| `control_uncertainty_calibration` | Player-adaptive holds 0.90 coverage at ~11.5% narrower intervals; fully development-internal | #62 |
| `control_residual_export` (record) | Control-regime `oos_residual_export_v1`: exactly 147 folds / 101,447 rows; preflight-clean | #59 |
| `candidate_residual_export` (record) | Calendar-aware `learned-rate-v2` half of the pair; control regenerated at the same commit and byte-identical across three commits | #80 |
| `time_aware_recalibration` | Held-out coverage **unchanged** on single gameweeks (0.9019 both) at **7.2% narrower** intervals; both regimes **undercover doubles** (0.83 / 0.80 vs nominal 0.90) | #82 |
| `recalibration_dry_run` (+note) | Preflight-gated time-aware pipeline proven on real fw05-vs-fw10 regimes; fw10 tighter at unchanged coverage | #63 |

## Planning

| Artifact | Finding | PR |
| --- | --- | --- |
| `multi_gw_rehearsal` | Planner vs myopic on real windows: +1.17 net points/window under naive projections | #66 |
| `planner_doe` | Horizon length is the live control (H2 +4.83 / H4 −3.67); hit cost matters only below 4; discount dead | #71 |
| `projection_horizon_run` (record) | First real multi-gameweek handoff; an opening capture yields a **flat** horizon because the published calendar has no blanks or doubles | #83 |
| `horizon_decay` | Projection MAE grows only **+7.8% over three gameweeks** (~2.6%/GW); doubles decay faster (+10.6%) than singles (+7.5%) — so the H4 planner loss is mostly **not** projection staleness | #85 |

## Process references

`handoff_acceptance_checklist.md` · `candidate_declaration_review.md` ·
`gw1_blocker_report_template.md` · `fw10_holdout_plan.md` · `opening_week_runbook.md` ·
`artifact_preflight_spec.md` · `projection_horizon_contract.md`

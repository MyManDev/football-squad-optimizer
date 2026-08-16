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
| `issue43_handoff_acceptance` + `issue43_stage_a_review` (records) | Handoff accepted item by item with independent re-runs at `93a87d6`: control export hash reproduces across machines, **candidate export does not** (BLAS-level last-bit differences; content identical to 4 dp); declaration fingerprints reproduce byte for byte; optimization-side Stage A review done, reading (a) confirmed, v2 clean enough to freeze; freeze pending the third owner | — |
| `issue38_calibration_decision` (record) | Operational calibration stays bound to the control's residuals; #38 closes with the #43 verdict either way; the shared double-gameweek undercoverage (0.83/0.80 vs 0.90) is a calibration fact — a fixture-group conformal axis is this layer's next measured step | — |
| `recalibration_dry_run` (+note) | Preflight-gated time-aware pipeline proven on real fw05-vs-fw10 regimes; fw10 tighter at unchanged coverage | #63 |

## Planning

| Artifact | Finding | PR |
| --- | --- | --- |
| `multi_gw_rehearsal` | Planner vs myopic on real windows: +1.17 net points/window under naive projections | #66 |
| `planner_doe` | Horizon length is the live control (H2 +4.83 / H4 −3.67); hit cost matters only below 4; discount dead | #71 |
| `projection_horizon_run` (record) | First real multi-gameweek handoff; an opening capture yields a **flat** horizon because the published calendar has no blanks or doubles | #83 |
| `horizon_decay` | Projection MAE grows only **+7.8% over three gameweeks** (~2.6%/GW); doubles decay faster (+10.6%) than singles (+7.5%) — so the H4 planner loss is mostly **not** projection staleness | #85 |
| `planner_horizon_seasons` (+note) | Four seasons / 23 windows per horizon: H2's +4.83 was one season (4-season mean −0.57); no horizon beats myopic beyond noise (SE 1.7–3.4); H4 −4.87 loses on **selection, not hits** (planner pays fewer hits than myopic), concentrated in windows with **no** calendar structure → information staleness at the top of the ranking, not calendar handling; wall-clock-capped, recommendation-quality | — |
| `export_precision` | Unrounded, **all 58,855 non-zero rows move** under a 1e-15 perturbation — why two owners hashed the same export differently; **9 dp moves none**, so the export now writes nine decimals | #94 |
| `candidate_runtime` | Checklist item 15: learned candidate **590 s** over 147 folds (4.02 s/fold) against the control's **11.7 s** — about fifty times the cost, projection-only, no solver | — |
| `opponent_strength_signal` | Control residuals still move with opponent strength: **+0.162** attacking (monotone), **+0.322** defensive; effect is *larger* after the model than before it (1.24x / 1.06x) — unspent signal | #87 |

## Process references

`handoff_acceptance_checklist.md` · `candidate_declaration_review.md` ·
`gw1_blocker_report_template.md` · `fw10_holdout_plan.md` · `opening_week_runbook.md` ·
`artifact_preflight_spec.md` · `projection_horizon_contract.md`

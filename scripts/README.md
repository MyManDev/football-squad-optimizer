# Scripts

One row per script, classified by what grep finds, not by what the name suggests: **shim** delegates to `src/squadopt`; **deprecated shell** is kept one release for old runbooks; **measurement runner** writes a committed `docs/` record (JSON, or the Markdown record the row names); **artifact-only runner** writes to git-ignored `artifacts/`, `data/`, or stdout; **operational** is named by a runbook, workflow, `run_week`, or platform code; **helper** is imported, not run; **fixture generator** regenerates a committed test fixture.
The three build shims `build_site`, `build_league_site` and `build_scoreboard` are load-bearing: `src/squadopt/platform/weekly_publish.py` subprocesses them. Run everything as `python -m scripts.<name>` from the repository root.
Date is the file's last commit (`git log -1 --format=%as -- scripts/<name>.py`).

| Script | Class | Record it writes, or what names it | Last commit |
| --- | --- | --- | --- |
| `_experiment_cli.py` | helper | imported by 74 runners: provenance metadata, `write_json`, `write_text` | 2026-09-09 |
| `_phase_e_checkpoints.py` | helper | imported by `probe_phase_e_runtime` | 2026-09-07 |
| `_phase_e_development.py` | helper | imported by `probe_phase_e_runtime`, `_phase_e_evaluation` | 2026-09-07 |
| `_phase_e_evaluation.py` | helper | imported by `run_phase_e_shadow` | 2026-09-07 |
| `_phase_e_inputs.py` | helper | imported by the Phase E runners and helpers | 2026-09-07 |
| `_phase_e_live.py` | helper | imported by `probe_phase_e_runtime`, `_phase_e_shadow_live` | 2026-09-07 |
| `_phase_e_shadow_live.py` | helper | imported by `run_phase_e_live_shadow` | 2026-09-07 |
| `append_weekly_scorecard.py` | measurement runner | `docs/weekly_scorecard.md` (Markdown record) | 2026-08-23 |
| `build_league_site.py` | shim (load-bearing) | subprocessed by `platform/weekly_publish.py`; `docs/weekly_runbook.md` | 2026-09-10 |
| `build_mode_price_list.py` | measurement runner | `docs/mode_price_list.json` | 2026-08-20 |
| `build_opponent_signal.py` | measurement runner | `docs/opponent_signal.json` | 2026-08-23 |
| `build_projection_handoff.py` | shim | `squadopt.application.projection_handoff`; `docs/weekly_runbook.md` | 2026-09-10 |
| `build_projection_horizon.py` | measurement runner | `docs/projection_horizon_run.md` (Markdown record); writes `data/handoffs/` | 2026-09-08 |
| `build_scoreboard.py` | shim (load-bearing) | subprocessed by `platform/weekly_publish.py`; `docs/weekly_runbook.md` | 2026-09-10 |
| `build_site.py` | shim (load-bearing) | subprocessed by `platform/weekly_publish.py`; `docs/weekly_runbook.md` | 2026-09-10 |
| `capture_deadline_snapshot.py` | deprecated shell | replaced by `squadopt season tick`; still named by `docs/opening_week_runbook.md` | 2026-09-07 |
| `capture_elite_picks.py` | shim | `squadopt.platform.elite_capture`; `docs/weekly_runbook.md` | 2026-09-10 |
| `capture_top100_cohort.py` | shim | `squadopt.platform.cohort_capture`; `docs/weekly_runbook.md` | 2026-09-10 |
| `compare_component_oof_development.py` | artifact-only runner | `--output-dir` (`comparison.json`, `comparison.md`) | 2026-09-07 |
| `evaluate_phase_c_components.py` | measurement runner | `docs/phase_c_component_evaluation.json` | 2026-09-05 |
| `export_candidate_residuals.py` | measurement runner | `docs/candidate_residual_export.md` (Markdown record); export in `artifacts/` | 2026-08-18 |
| `export_component_oof.py` | artifact-only runner | `artifacts/phase_c/` | 2026-09-07 |
| `export_control_residuals.py` | measurement runner | `docs/control_residual_export.md` (Markdown record); export in `artifacts/` | 2026-08-18 |
| `export_in_season_residuals.py` | measurement runner | `docs/in_season_residual_export.md` (Markdown record); export in `artifacts/` | 2026-08-31 |
| `export_player_evidence.py` | shim | `squadopt.application.player_evidence`; `docs/weekly_runbook.md` | 2026-09-10 |
| `export_rotation_evidence.py` | shim | `squadopt.application.rotation_export`; `docs/weekly_runbook.md` | 2026-09-11 |
| `export_settled_outcomes.py` | shim | `squadopt.application.settled_outcomes` | 2026-09-10 |
| `fetch_historical_data.py` | operational | `docs/data_pipeline.md`; named by `data/sources/vaastav.py` and 20 runners | 2026-08-14 |
| `freeze_candidate_declaration.py` | measurement runner | `docs/issue43_candidate_declaration.json` | 2026-08-19 |
| `freeze_route_a_declaration.py` | measurement runner | `docs/route_a_declaration.json` | 2026-08-23 |
| `generate_club_news_coding_fixture.py` | fixture generator | committed coding fixture; `docs/rotation_claim_coding.md` | 2026-09-10 |
| `generate_club_news_fixture.py` | fixture generator | committed club-news fixture | 2026-09-08 |
| `generate_sample_data.py` | fixture generator | `data/sample/`; `docs/data_pipeline.md` | 2026-08-11 |
| `measure_anchored_calibration.py` | measurement runner | `docs/anchored_calibration.json` | 2026-08-23 |
| `measure_benchmark_v2.py` | measurement runner | `docs/benchmark_v2.json` | 2026-09-01 |
| `measure_candidate_runtime.py` | measurement runner | `docs/candidate_runtime.json` | 2026-08-16 |
| `measure_capture_lead_time.py` | measurement runner | `docs/capture_lead_time.json`; also `docs/weekly_runbook.md` | 2026-09-08 |
| `measure_capture_season_phase.py` | measurement runner | `docs/capture_season_phase.json` | 2026-09-08 |
| `measure_component_fidelity.py` | measurement runner | `docs/phase_d_component_fidelity.json` | 2026-09-07 |
| `measure_export_precision.py` | measurement runner | `docs/export_precision.json` | 2026-08-16 |
| `measure_in_season_blend.py` | measurement runner | `docs/in_season_blend_benchmark.json` | 2026-08-23 |
| `measure_mode_plan_selection.py` | measurement runner | `docs/mode_plan_selection.json` | 2026-09-10 |
| `measure_opening_prior_exposure.py` | measurement runner | `docs/opening_prior_exposure.json` | 2026-08-28 |
| `measure_overlap_calibration.py` | measurement runner | `docs/overlap_calibration.json` | 2026-08-23 |
| `measure_rival_calibration.py` | measurement runner | `docs/rival_calibration.json` | 2026-08-23 |
| `measure_rotation_ceiling.py` | measurement runner | `docs/rotation_oracle_ceiling.json` | 2026-09-09 |
| `measure_scenario_path_dependence.py` | measurement runner | `docs/scenario_path_dependence.json` | 2026-08-19 |
| `measure_strategy_bench.py` | measurement runner | `docs/strategy_bench.json` | 2026-09-10 |
| `measure_strategy_screening.py` | measurement runner | `docs/strategy_screening.json` | 2026-08-31 |
| `measure_template_rival.py` | measurement runner | `docs/template_rival_strength.json` (+ per-season variants) | 2026-08-19 |
| `measure_windowed_rank.py` | measurement runner | `docs/windowed_rank.json` | 2026-08-20 |
| `plan_transfer_horizon.py` | artifact-only runner | `data/handoffs/`; `docs/projection_horizon_contract.md` | 2026-08-31 |
| `probe_phase_e_runtime.py` | artifact-only runner | checkpoints via `_phase_e_checkpoints`; prereg `docs/phase_e_candidate_selection_prereg.md` | 2026-09-07 |
| `publish_gameweek_site.py` | shim | `squadopt.platform.weekly_publish`; `docs/weekly_runbook.md` | 2026-09-10 |
| `recommend_current_squad.py` | operational | `docs/opening_week_runbook.md`, `docs/gw1_run_sheet.md`, `docs/gw2_run_sheet.md` | 2026-09-07 |
| `record_preseason_difficulty.py` | measurement runner | `docs/preseason_fixture_difficulty.json`; also `docs/gw1_run_sheet.md` | 2026-09-07 |
| `run_artifact_preflight.py` | operational | `docs/recalibration_runbook.md`; validates, writes nothing by default | 2026-08-15 |
| `run_baseline_bayesopt.py` | artifact-only runner | `artifacts/bayesopt/` | 2026-08-15 |
| `run_baseline_benchmark.py` | artifact-only runner | `--json-output` only, no `docs/` path in the script; `docs/baseline_benchmark.md` names it | 2026-08-14 |
| `run_calendar_recalibration.py` | operational | `docs/recalibration_runbook.md`; `--json-output` only | 2026-08-15 |
| `run_candidate_gate.py` | measurement runner | `docs/issue43_candidate_declaration.json` (reads and judges); `docs/candidate_gate_spec.md` | 2026-08-19 |
| `run_captain_attribution.py` | measurement runner | `docs/phase2_captain_attribution.json` | 2026-08-31 |
| `run_chip_bayesopt.py` | measurement runner | `docs/chip_bayesopt.json` (+ `_value`, `_wide` variants) | 2026-08-18 |
| `run_component_squad_calibration.py` | measurement runner | `docs/phase_d_component_squad_calibration.json` | 2026-09-07 |
| `run_control_uncertainty_calibration.py` | measurement runner | `docs/control_uncertainty_calibration.json` (+ `_v2`) | 2026-08-18 |
| `run_exhaustive_policy_grid.py` | measurement runner | `docs/baseline_policy_grid.json`, `docs/baseline_bayesopt.json` | 2026-08-15 |
| `run_fixture_group_conformal.py` | measurement runner | `docs/fixture_group_conformal.json` | 2026-08-20 |
| `run_frozen_holdout.py` | artifact-only runner | `artifacts/sprint2/holdout.json`; `docs/fw10_holdout.json` shares the stem | 2026-08-13 |
| `run_fw10_season_robustness.py` | measurement runner | `docs/fw10_season_robustness.json` | 2026-08-16 |
| `run_gameweek_ops.py` | deprecated shell | replaced by `squadopt gameweek decide` / `settle`; `docs/architecture/platform_runtime.md` | 2026-08-20 |
| `run_horizon_decay.py` | measurement runner | `docs/horizon_decay.json` | 2026-09-08 |
| `run_learned_benchmark.py` | artifact-only runner | `artifacts/sprint6/`; `docs/learned_prediction_spec.md` names it | 2026-08-13 |
| `run_live_calibration.py` | artifact-only runner | `docs/live_calibration_gwNN.json` (none committed yet) | 2026-08-16 |
| `run_measurement_preflight.py` | operational | validates a `docs/*.json` record; ADR 0003, `docs/measurements_index.md` | 2026-08-16 |
| `run_multi_gw_rehearsal.py` | measurement runner | `docs/multi_gw_rehearsal.json` | 2026-08-15 |
| `run_opening_backtest.py` | measurement runner | `docs/opening_backtest.json` | 2026-08-16 |
| `run_opening_newcomer_study.py` | measurement runner | `docs/opening_newcomer_study.json` | 2026-08-19 |
| `run_opening_prior_backtest.py` | artifact-only runner | `artifacts/opening_prior/`; `docs/data_pipeline.md`, `prediction/config.py` name it | 2026-08-13 |
| `run_opponent_projection_study.py` | measurement runner | `docs/opponent_projection_study.json` | 2026-08-19 |
| `run_opponent_strength_signal.py` | measurement runner | `docs/opponent_strength_signal.json` | 2026-08-16 |
| `run_phase_e_live_shadow.py` | artifact-only runner | E4 decide entry point; named by nothing | 2026-09-05 |
| `run_phase_e_shadow.py` | artifact-only runner | `--json-output` (internal destination) | 2026-09-07 |
| `run_planner_doe.py` | measurement runner | `docs/planner_doe.json` | 2026-08-16 |
| `run_planner_horizon_seasons.py` | measurement runner | `docs/planner_horizon_seasons.json` | 2026-08-17 |
| `run_player_risk_screening.py` | artifact-only runner | `artifacts/sprint5/`; `docs/player_uncertainty_spec.md` names it | 2026-08-13 |
| `run_production_benchmark.py` | artifact-only runner | `--json-output` only, no `docs/` path in the script | 2026-08-14 |
| `run_rank_objective_rehearsal.py` | measurement runner | `docs/rank_objective_rehearsal.json` (+ `_heldout`) | 2026-08-18 |
| `run_residual_signal_scan.py` | measurement runner | `docs/residual_signal_scan.json` | 2026-08-17 |
| `run_risk_frontier.py` | measurement runner | `docs/risk_frontier.json` (+ `_shrunk`) | 2026-08-16 |
| `run_risk_screening.py` | artifact-only runner | `artifacts/sprint4/`; `docs/risk_optimization_spec.md` names it | 2026-08-18 |
| `run_scenario_audit.py` | measurement runner | `docs/scenario_calibration_audit.json` (+ variants) | 2026-08-18 |
| `run_scenario_bayesopt.py` | measurement runner | `docs/scenario_bayesopt.json` (+ `_deterministic`) | 2026-08-15 |
| `run_scenario_benchmark.py` | artifact-only runner | `artifacts/sprint7/`; `docs/scenario_spec.md` names it | 2026-08-13 |
| `run_schedule_signal_study.py` | measurement runner | `docs/schedule_signal_study.json` | 2026-08-19 |
| `run_screening_doe.py` | artifact-only runner | `artifacts/sprint2/screening.json`; `docs/fw10_screening.json` shares the stem | 2026-08-13 |
| `run_season_chain_seasons.py` | measurement runner | `docs/season_chain.json` (+ variants), `docs/planner_horizon_rolling.json` | 2026-09-07 |
| `run_season_tick.py` | deprecated shell | replaced by `squadopt season tick`; `docs/architecture/platform_runtime.md` | 2026-08-20 |
| `run_selection_optimism.py` | measurement runner | `docs/selection_optimism.json` | 2026-08-16 |
| `run_shadow_calibration.py` | measurement runner | `docs/shadow_calibration_in_season.json` | 2026-08-31 |
| `run_shadow_squad_calibration.py` | measurement runner | `docs/shadow_calibration_squad.json`, `docs/shadow_calibration_in_season_corrected.json` | 2026-08-31 |
| `run_shrinkage_grid.py` | measurement runner | `docs/shrinkage_grid.json` | 2026-08-16 |
| `run_tail_diagnostic.py` | measurement runner | `docs/phase2_tail_diagnostic.json` | 2026-08-31 |
| `run_team_rating_cs_remeasure.py` | measurement runner | `docs/team_rating_cs_remeasure.json` | 2026-08-20 |
| `run_team_rating_study.py` | measurement runner | `docs/team_rating_study.json` | 2026-08-19 |
| `run_terminal_value_study.py` | measurement runner | `docs/terminal_value_study.json` | 2026-08-20 |
| `run_transfer_discipline_seasons.py` | measurement runner | `docs/transfer_discipline.json` (+ rolling variants) | 2026-08-18 |
| `run_transfer_horizon_batch.py` | artifact-only runner | `artifacts/live/`; `docs/projection_horizon_contract.md` | 2026-08-31 |
| `run_uncertainty_benchmark.py` | artifact-only runner | `artifacts/sprint3/`; `docs/uncertainty_spec.md` names it | 2026-08-13 |
| `run_week.py` | shim | `squadopt.platform.weekly_operations`; `docs/weekly_runbook.md` | 2026-09-10 |
| `seed_entry_registry.py` | operational | `data/entries/registry.json`; `docs/weekly_runbook.md` | 2026-09-07 |

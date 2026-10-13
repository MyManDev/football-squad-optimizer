# Scripts

One row per script, classified by what grep finds, not by what the name suggests: **shim** delegates to `src/squadopt`; **deprecated shell** is kept one release for old runbooks; **measurement runner** writes a committed `docs/` record (JSON, or the Markdown record the row names); **artifact-only runner** writes to git-ignored `artifacts/`, `data/`, or stdout; **operational** is named by a runbook, workflow, `run_week`, or platform code; **helper** is imported, not run; **fixture generator** regenerates a committed test fixture.
Run everything as `python -m scripts.<name>` from the repository root.
Date is the file's last commit (`git log -1 --format=%as -- scripts/<name>.py`).

| Purpose | Catalog section |
| --- | --- |
| Operational commands | [Operational commands](#operational-commands) |
| Measurement runners | [Measurement runners](#measurement-runners) |
| Artifact-only runners | [Artifact-only runners](#artifact-only-runners) |
| Fixture generators | [Fixture generators](#fixture-generators) |
| Imported helpers | [Imported helpers](#imported-helpers) |
| Deprecated compatibility commands | [Deprecated compatibility commands](#deprecated-compatibility-commands) |
| Retired runners | [Retired runners](#retired-runners) |

## Operational commands

| Script | Class | Record it writes, or what names it | Last commit |
| --- | --- | --- | --- |
| `add_device_plan_inputs.py` | operational | `docs/contracts/league_device_plan_v1.md`; `docs/weekly_runbook.md` | 2026-10-11 |
| `build_league_site.py` | shim | `squadopt.application.league_publication`; `docs/weekly_runbook.md` | 2026-09-10 |
| `build_projection_handoff.py` | shim | `squadopt.application.projection_handoff`; `docs/weekly_runbook.md` | 2026-09-10 |
| `build_scoreboard.py` | shim | `squadopt.application.scoreboard`; `docs/weekly_runbook.md` | 2026-09-10 |
| `build_site.py` | shim | `squadopt.application.site_publication`; `docs/weekly_runbook.md` | 2026-09-10 |
| `capture_club_news.py` | shim | `squadopt.platform.club_news_acquire`; `docs/weekly_runbook.md` | 2026-09-15 |
| `capture_elite_picks.py` | shim | `squadopt.platform.elite_capture`; `docs/weekly_runbook.md` | 2026-09-10 |
| `capture_top100_cohort.py` | shim | `squadopt.platform.cohort_capture`; `docs/weekly_runbook.md` | 2026-09-10 |
| `export_player_evidence.py` | shim | `squadopt.application.player_evidence`; `docs/weekly_runbook.md` | 2026-09-10 |
| `export_rotation_evidence.py` | shim | `squadopt.application.rotation_export`; `docs/weekly_runbook.md` | 2026-09-11 |
| `export_settled_outcomes.py` | shim | `squadopt.application.settled_outcomes` | 2026-09-10 |
| `fetch_historical_data.py` | operational | `docs/data_pipeline.md`; named by `data/sources/vaastav.py` and six scripts | 2026-08-14 |
| `publish_gameweek_site.py` | shim | `squadopt.platform.weekly_publish`; `docs/weekly_runbook.md` | 2026-09-10 |
| `recommend_current_squad.py` | operational | `docs/opening_week_runbook.md`, `docs/gw1_run_sheet.md`, `docs/gw2_run_sheet.md` | 2026-09-07 |
| `run_artifact_preflight.py` | operational | `docs/recalibration_runbook.md`; validates, writes nothing by default | 2026-08-15 |
| `run_backend_local.ps1` | operational | `docs/backend_free_hosting.md`; PowerShell, run directly; writes only under git-ignored `data/runtime/backend` | 2026-09-17 |
| `run_calendar_recalibration.py` | operational | `docs/recalibration_runbook.md`; `--json-output` only | 2026-08-15 |
| `run_measurement_preflight.py` | operational | validates a `docs/*.json` record; ADR 0003, `docs/measurements_index.md` | 2026-08-16 |
| `run_week.py` | shim | `squadopt.platform.weekly_operations`; `docs/weekly_runbook.md` | 2026-09-10 |
| `seed_entry_registry.py` | operational | `data/entries/registry.json`; `docs/weekly_runbook.md` | 2026-09-07 |
| `smoke_backend_local.py` | operational | `docs/backend_free_hosting.md`; standard library only, writes nothing | 2026-09-17 |

## Measurement runners

| Script | Class | Record it writes, or what names it | Last commit |
| --- | --- | --- | --- |
| `append_weekly_scorecard.py` | measurement runner | `docs/weekly_scorecard.md` (Markdown record) | 2026-08-23 |
| `build_mode_price_list.py` | measurement runner | `docs/mode_price_list.json` | 2026-08-20 |
| `build_projection_horizon.py` | measurement runner | `docs/projection_horizon_run.md` (Markdown record); writes `data/handoffs/` | 2026-09-08 |
| `evaluate_phase_c_components.py` | measurement runner | `docs/phase_c_component_evaluation.json` | 2026-09-05 |
| `export_candidate_residuals.py` | measurement runner | `docs/candidate_residual_export.md` (Markdown record); export in `artifacts/` | 2026-08-18 |
| `export_control_residuals.py` | measurement runner | `docs/control_residual_export.md` (Markdown record); export in `artifacts/` | 2026-08-18 |
| `freeze_candidate_declaration.py` | measurement runner | `docs/issue43_candidate_declaration.json` | 2026-08-19 |
| `measure_anchored_calibration.py` | measurement runner | `docs/anchored_calibration.json` | 2026-08-23 |
| `measure_benchmark_v2.py` | measurement runner | `docs/benchmark_v2.json` | 2026-09-01 |
| `measure_capture_lead_time.py` | measurement runner | `docs/capture_lead_time.json`; also `docs/weekly_runbook.md` | 2026-09-08 |
| `measure_component_fidelity.py` | measurement runner | `docs/phase_d_component_fidelity.json` | 2026-09-07 |
| `measure_defcon_component.py` | measurement runner | outcome-free identity check; one owner-authorized `docs/research/defcon_component_reading.{json,md}` record under #1000 | 2026-10-10 |
| `measure_double_reduction.py` | measurement runner | `docs/double_reduction.json`, `docs/double_reduction.md` | 2026-09-25 |
| `measure_football_shares.py` | measurement runner | `docs/research/football_share_sizing.json`; summary and player-fixture table in `artifacts/` | 2026-10-09 |
| `measure_in_season_blend.py` | measurement runner | `docs/in_season_blend_benchmark.json` | 2026-08-23 |
| `measure_mode_plan_selection.py` | measurement runner | `docs/mode_plan_selection.json` | 2026-09-10 |
| `measure_opening_prior_exposure.py` | measurement runner | `docs/opening_prior_exposure.json` | 2026-08-28 |
| `measure_overlap_calibration.py` | measurement runner | `docs/overlap_calibration.json` | 2026-08-23 |
| `measure_participation_calibration.py` | measurement runner | `docs/participation_calibration.json`, `docs/participation_calibration.md` | 2026-09-16 |
| `measure_rival_calibration.py` | measurement runner | `docs/rival_calibration.json` | 2026-08-23 |
| `measure_rotation_ceiling.py` | measurement runner | `docs/rotation_oracle_ceiling.json` | 2026-09-09 |
| `measure_scenario_path_dependence.py` | measurement runner | `docs/scenario_path_dependence.json` | 2026-08-19 |
| `measure_strategy_bench.py` | measurement runner | `docs/strategy_bench.json` | 2026-09-10 |
| `measure_strategy_rule_scale.py` | measurement runner | `docs/strategy_rule_scale.json`, `docs/strategy_rule_scale.md` | 2026-10-10 |
| `measure_strategy_screening.py` | measurement runner | `docs/strategy_screening.json` | 2026-08-31 |
| `measure_template_rival.py` | measurement runner | `docs/template_rival_strength.json` (+ per-season variants) | 2026-08-19 |
| `measure_window_solver_highs.py` | measurement runner | `docs/research/window_solver_highs.json`, `docs/research/window_solver_highs.md`; `check` writes only `artifacts/window_solver_highs/`; protocol `docs/window_solver_highs_prereg.md` | 2026-10-06 |
| `read_benchmark_v2_live.py` | measurement runner | `docs/benchmark-v2-live-2026-27.json` and its Markdown twin, with the claim `docs/benchmark-v2-live-2026-27.reading` | 2026-10-10 |
| `record_preseason_difficulty.py` | measurement runner | `docs/preseason_fixture_difficulty.json`; also `docs/gw1_run_sheet.md` | 2026-09-07 |
| `run_candidate_gate.py` | measurement runner | `docs/issue43_candidate_declaration.json` (reads and judges); `docs/candidate_gate_spec.md` | 2026-08-19 |
| `run_component_squad_calibration.py` | measurement runner | `docs/phase_d_component_squad_calibration.json` | 2026-09-07 |
| `run_opening_backtest.py` | measurement runner | `docs/opening_backtest.json` | 2026-08-16 |
| `run_opponent_projection_study.py` | measurement runner | `docs/opponent_projection_study.json` | 2026-08-19 |
| `run_planner_horizon_seasons.py` | measurement runner | `docs/planner_horizon_seasons.json` | 2026-08-17 |
| `run_season_chain_seasons.py` | measurement runner | `docs/season_chain.json` (+ variants), `docs/planner_horizon_rolling.json` | 2026-09-07 |
| `run_terminal_value_study.py` | measurement runner | `docs/terminal_value_study.json` | 2026-08-20 |
| `run_transfer_discipline_seasons.py` | measurement runner | `docs/transfer_discipline.json` (+ rolling variants) | 2026-08-18 |
| `score_planner_policy_chain.py` | measurement runner | `docs/research/planner_policy_chain_gw20.json` and `planner_policy_chain_gw38.json` with their markdown twins, each once, from the chain runner's evidence, the receipts posted on the tracking issue (`--receipts`, `--producer-changes`) and the season's outcome captures; needs a clean, non-shallow clone that reaches origin; protocol `docs/research/planner_policy_chain_prereg.md`, rules 2, 3, 6, 13, 14 and 20 to 37 | 2026-10-08 |

## Artifact-only runners

| Script | Class | Record it writes, or what names it | Last commit |
| --- | --- | --- | --- |
| `build_football_shadow.py` | artifact-only runner | `artifacts/shadow/football_team_share_v1/{football,receipts}/<capture>.json`; `docs/football_prospective_shadow_note.md`, #999 | 2026-10-07 |
| `compare_component_oof_development.py` | artifact-only runner | `--output-dir` (`comparison.json`, `comparison.md`) | 2026-09-07 |
| `export_component_oof.py` | artifact-only runner | `artifacts/phase_c/` | 2026-09-07 |
| `export_decided_appearance.py` | artifact-only runner | `artifacts/double_reduction/`; the `--fitted` input of `measure_double_reduction.py` | 2026-09-25 |
| `measure_availability_transitions.py` | artifact-only runner | a fresh `--output` directory the operator names (`record.json`, `summary.md`); refuses the snapshot root and the repository's `data/` and `docs/`; protocol `docs/availability_transitions_prereg.md` | 2026-10-01 |
| `measure_football_lead_reliability.py` | artifact-only runner | a fresh `--output` directory the operator names (`record.json`, `summary.md`, `forecasts.csv`); refuses the archive and the repository's `data/` and `docs/`; protocol `docs/football_lead_reliability_prereg.md` | 2026-10-06 |
| `measure_planner_policy_chain.py` | artifact-only runner | `artifacts/planner_policy_chain/` (receipts, forecast copies, decision records, weekly manifests), each week copied to `--evidence-copy-root` outside the checkout; reads no outcome; protocol `docs/research/planner_policy_chain_prereg.md` | 2026-10-06 |
| `measure_published_difficulty_live.py` | artifact-only runner | private JSON/CSV under ignored `artifacts/`; usage in `docs/research/published_difficulty_live_runner.md`; one reading after settled GW20 | 2026-10-11 |
| `plan_transfer_horizon.py` | artifact-only runner | `data/handoffs/`; `docs/projection_horizon_contract.md` | 2026-08-31 |
| `probe_phase_e_runtime.py` | artifact-only runner | checkpoints via `_phase_e_checkpoints`; prereg `docs/phase_e_candidate_selection_prereg.md` | 2026-09-07 |
| `run_live_calibration.py` | artifact-only runner | `docs/live_calibration_gwNN.json` (none committed yet) | 2026-08-16 |
| `run_opening_prior_backtest.py` | artifact-only runner | `artifacts/opening_prior/`; `docs/data_pipeline.md`, `prediction/config.py` name it | 2026-08-13 |
| `run_phase_e_live_shadow.py` | artifact-only runner | E4 decide entry point; named by nothing | 2026-09-05 |
| `run_phase_e_shadow.py` | artifact-only runner | `--json-output` (internal destination) | 2026-09-07 |
| `run_transfer_horizon_batch.py` | artifact-only runner | `artifacts/live/`; `docs/projection_horizon_contract.md` | 2026-08-31 |

## Fixture generators

| Script | Class | Record it writes, or what names it | Last commit |
| --- | --- | --- | --- |
| `export_chip_forecast_fixture.py` | fixture generator | `web/src/fixtures/chip-forecast/cases.json`; #1003 | 2026-10-10 |
| `export_official_scoring_vectors.py` | fixture generator | `web/src/features/liveScore/officialScoring.vectors.json`; synthetic official finished-week scores for #1008 | 2026-10-10 |
| `generate_club_news_coding_fixture.py` | fixture generator | committed coding fixture; `docs/rotation_claim_coding.md` | 2026-09-10 |
| `generate_club_news_fixture.py` | fixture generator | committed club-news fixture | 2026-09-08 |
| `generate_sample_data.py` | fixture generator | `data/sample/`; `docs/data_pipeline.md` | 2026-08-11 |

After exporting official scoring vectors, run
`npx prettier --write src/features/liveScore/officialScoring.vectors.json` from
`web`. The drift test compares parsed JSON, preserving the Python answers while
allowing the web formatter's layout.

## Imported helpers

| Script | Class | Record it writes, or what names it | Last commit |
| --- | --- | --- | --- |
| `_experiment_cli.py` | helper | imported by every runner that `git grep -l "from scripts._experiment_cli import" -- 'scripts/*.py' \| wc -l` counts: provenance metadata, `write_json`, `write_text` | 2026-09-09 |
| `_phase_e_checkpoints.py` | helper | imported by `probe_phase_e_runtime` | 2026-09-07 |
| `_phase_e_development.py` | helper | imported by `probe_phase_e_runtime`, `_phase_e_evaluation` | 2026-09-07 |
| `_phase_e_evaluation.py` | helper | imported by `run_phase_e_shadow` | 2026-09-07 |
| `_phase_e_inputs.py` | helper | imported by the Phase E runners and helpers | 2026-09-07 |
| `_phase_e_live.py` | helper | imported by `probe_phase_e_runtime`, `_phase_e_shadow_live` | 2026-09-07 |
| `_phase_e_shadow_live.py` | helper | imported by `run_phase_e_live_shadow` | 2026-09-07 |
| `_provenance.py` | helper | imported by `_experiment_cli` and by the operational commands that must not load the laboratory: repository root, git revision, `write_json`, `write_text`; standard library only | 2026-09-26 |

## Retired compatibility commands

The one-release compatibility window ended with 1.0.0. These shells have been removed;
historical runbooks retain their original commands as records of those runs.

| Removed script | Current command |
| --- | --- |
| `capture_deadline_snapshot.py` | `squadopt season tick --dry-run` to inspect due actions, then `squadopt season tick` to execute them |
| `run_gameweek_ops.py` | `squadopt gameweek decide` / `squadopt gameweek settle --gameweek N` |
| `run_season_tick.py` | `squadopt season tick` |

A season tick can capture, decide and settle; it is not a capture-only replacement.
Dry-run records CLI bookkeeping but does not execute those due actions.

## Retired runners

These runners were removed on 2026-10-12. Each belonged to a study whose conclusion is final,
and no open issue or pull request plans to run it again (#590 names some of them in its sweep
of solver limits, and none of them is on its re-run list). Most wrote a committed record under
`docs/`, and those records stay; the last column says where a runner's output went when it
wrote none of its own. `git show <sha>:<path>` prints a runner's source, where the path is
`scripts/` followed by the file name. The source alone does not run on the current tree,
because much of the lab code the runners imported was removed with them. To run one, check out
the tree from before the removal in a separate worktree, `git worktree add <dir> <removal>^`,
where `<removal>` is what `git log -1 --diff-filter=D --format=%h -- scripts/<name>.py` prints.

| Script | Last commit | Record it wrote |
| --- | --- | --- |
| `build_opponent_signal.py` | 37bb590a | `docs/opponent_signal.json` |
| `export_in_season_residuals.py` | 3c29620a8 | `docs/in_season_residual_export.md` (Markdown record); export in `artifacts/` |
| `freeze_route_a_declaration.py` | 8949846ae | `docs/route_a_declaration.json` |
| `measure_candidate_runtime.py` | c0d23e48c | `docs/candidate_runtime.json` |
| `measure_capture_season_phase.py` | 039d1d181 | `docs/capture_season_phase.json` |
| `measure_export_precision.py` | b940c5eac | `docs/export_precision.json` |
| `measure_instrument.py` | cbd1a09b4 | caller-selected `--output`; replay in `docs/measurement_instrument.md` |
| `measure_opening_two_part.py` | 6270faf77 | `docs/opening_two_part.json`, `docs/opening_two_part.md` |
| `measure_rank_proofs.py` | 130706a07 | `docs/rank_proofs.json`, `docs/rank_proofs.md` |
| `measure_windowed_rank.py` | 1550a54c9 | `docs/windowed_rank.json` |
| `run_baseline_bayesopt.py` | 60c77fc7a | `artifacts/bayesopt/` |
| `run_baseline_benchmark.py` | 1b0c64da5 | `--json-output` only, no `docs/` path in the script; `docs/baseline_benchmark.md` names it |
| `run_captain_attribution.py` | 6b2a992bc | `docs/phase2_captain_attribution.json` |
| `run_chip_bayesopt.py` | b031ef188 | `docs/chip_bayesopt.json` (+ `_value`, `_wide` variants) |
| `run_control_uncertainty_calibration.py` | af6b14c34 | `docs/control_uncertainty_calibration.json` (+ `_v2`) |
| `run_exhaustive_policy_grid.py` | 7de5db0df | `docs/baseline_policy_grid.json`, `docs/baseline_bayesopt.json` |
| `run_fixture_group_conformal.py` | 84d95e090 | `docs/fixture_group_conformal.json` |
| `run_frozen_holdout.py` | 0ad2bfbbd | `artifacts/sprint2/holdout.json`; `docs/fw10_holdout.json` shares the stem |
| `run_fw10_season_robustness.py` | a31a2cc02 | `docs/fw10_season_robustness.json` |
| `run_horizon_decay.py` | 37bb590a | `docs/horizon_decay.json` |
| `run_learned_benchmark.py` | d1224b122 | `artifacts/sprint6/`; `docs/learned_prediction_spec.md` names it; `docs/learned_benchmark_development.json` names no commit and arrived in 955a5f53 |
| `run_multi_gw_rehearsal.py` | 7ff95f1a8 | `docs/multi_gw_rehearsal.json` |
| `run_opening_newcomer_study.py` | b96cf4063 | `docs/opening_newcomer_study.json` |
| `run_opponent_strength_signal.py` | d9eb8c4e3 | `docs/opponent_strength_signal.json` |
| `run_planner_doe.py` | acfcb0fa9 | `docs/planner_doe.json` |
| `run_player_risk_screening.py` | 0e42d674f | `artifacts/sprint5/`; `docs/player_uncertainty_spec.md` names it |
| `run_production_benchmark.py` | 51fb6d1e6 | `--json-output` only, no `docs/` path in the script; `docs/production_gate_judgement.json` names no commit, and ba453537 (#44) made it reproducible |
| `run_rank_objective_rehearsal.py` | ee9c6c0f0 | `docs/rank_objective_rehearsal.json` (+ `_heldout`) |
| `run_residual_signal_scan.py` | 240ddcb88 | `docs/residual_signal_scan.json` |
| `run_risk_frontier.py` | a96fe3be6 | `docs/risk_frontier.json` (+ `_shrunk`) |
| `run_risk_screening.py` | 1b0c64da5 | `artifacts/sprint4/`; `docs/risk_optimization_spec.md` names it |
| `run_scenario_audit.py` | 0b2c97a49 | `docs/scenario_calibration_audit.json` (+ variants) |
| `run_scenario_bayesopt.py` | 290332b27 | `docs/scenario_bayesopt.json` (+ `_deterministic`) |
| `run_scenario_benchmark.py` | 59838a51b | `artifacts/sprint7/`; `docs/scenario_spec.md` names it |
| `run_schedule_signal_study.py` | dda802287 | `docs/schedule_signal_study.json` |
| `run_screening_doe.py` | 0ad2bfbbd | `artifacts/sprint2/screening.json`; `docs/fw10_screening.json` shares the stem |
| `run_selection_optimism.py` | c2a0c5433 | `docs/selection_optimism.json` |
| `run_shadow_calibration.py` | 3c29620a8 | `docs/shadow_calibration_in_season.json` |
| `run_shadow_squad_calibration.py` | c1f882bf3 | `docs/shadow_calibration_squad.json`, `docs/shadow_calibration_in_season_corrected.json` |
| `run_shrinkage_grid.py` | a96fe3be6 | `docs/shrinkage_grid.json` |
| `run_tail_diagnostic.py` | 217c41f47 | `docs/phase2_tail_diagnostic.json` |
| `run_team_rating_cs_remeasure.py` | 50ea8e431 | `docs/team_rating_cs_remeasure.json` |
| `run_team_rating_study.py` | c7f341250 | `docs/team_rating_study.json` |
| `run_uncertainty_benchmark.py` | 1b0c64da5 | `artifacts/sprint3/`; `docs/uncertainty_spec.md` names it |

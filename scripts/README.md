# Scripts

The repository's commands that are not part of the installed package: operator commands, the
release recipe, the Windows backend scripts, measurement runners, generators and the helpers
they import. **Every file under `scripts/` has exactly one row in this catalogue**, keyed by its
path relative to this folder, and a pull request that adds, removes or renames a file edits its
row in the same change; `tests/architecture/test_scripts_catalogue.py` fails until it does, and
holds a row of the two retired sections to a file that is gone. A row is classified by what the
code does, not by what its name suggests.

Run a Python script as `python -m scripts.<name>` from the repository root, a file under
`release/` as `python scripts/release/<name>.py` or `sh scripts/release/<name>.sh`, and a
PowerShell script as `powershell -ExecutionPolicy Bypass -File scripts\<name>.ps1`. The last
column is the author date of the file's last commit when this catalogue was last edited;
`git log -1 --format=%as -- scripts/<path>` prints the current one.

| Role | What it means |
| --- | --- |
| operational | An operator command, named by a runbook, a workflow or platform code. It imports product packages only, apart from the three laboratory tools that `LABORATORY_TOOLS` names: `tests/architecture/test_run_boundary.py` imports every other `.py` row of the operational table and fails if one loads a laboratory module. |
| shim | An operational command that only delegates to a function in `src/squadopt`. |
| release recipe | A step of the human-gated release that cuts, deploys and verifies a `site-*` release, or prepares a pull request body for the merge queue. |
| Windows backend | A PowerShell script that runs or watches the advice backend on the owner's Windows PC, or backs up the private data it serves from. |
| measurement runner | Produces a committed record under `docs/`: written there directly, or written to an output directory and committed as a record that names this file. |
| artifact-only runner | Writes to git-ignored `artifacts/` or `data/`, to an output directory the operator names, or to stdout, and writes no committed record of its own. |
| fixture generator | Regenerates a committed test fixture. |
| code generator | Regenerates a committed source file. |
| helper | Imported by other scripts, not run. |

| Purpose | Catalogue section |
| --- | --- |
| Operator commands | [Operational commands](#operational-commands) |
| Cut, deploy and verify a release | [Release recipe](#release-recipe) |
| Run, watch and back up the backend on Windows | [Windows backend and data backup](#windows-backend-and-data-backup) |
| Measurement runners | [Measurement runners](#measurement-runners) |
| Artifact-only runners | [Artifact-only runners](#artifact-only-runners) |
| Fixture and code generators | [Fixture and code generators](#fixture-and-code-generators) |
| Imported helpers | [Imported helpers](#imported-helpers) |
| Commands removed with 1.0.0 | [Retired compatibility commands](#retired-compatibility-commands) |
| Runners of concluded studies, removed | [Retired runners](#retired-runners) |

## Operational commands

| Script | Class | Record it writes, or what names it | Last commit |
| --- | --- | --- | --- |
| `add_device_plan_inputs.py` | operational | `docs/contracts/league_device_plan_v1.md`; `docs/weekly_runbook.md` | 2026-10-12 |
| `backend_status.py` | operational | reads the backend's `/ready`, `/metrics` and `/health` answers and the operator logs under `data/runtime/backend/logs`, and prints a summary; `docs/backend_runbook.md`, `docs/deployment_runbook.md` | 2026-09-28 |
| `build_football_forecast.py` | operational | the optional football forecast of one capture, under `--artifact-root` through `squadopt.platform.football_publication`; explicit paired retained captures can fit first-week categorical flags (`scripts/build_football_forecast.py:88`); [procedure](../docs/operations/retained_flag_forecasts.md) | 2026-10-15 |
| `build_league_site.py` | shim | `squadopt.application.league_publication`; `docs/weekly_runbook.md` | 2026-10-09 |
| `build_player_catalog.py` | operational | `data/players.json` under the site directory `--out`, for the contribution form; `docs/contributions.md`, `docs/deployment_runbook.md` | 2026-09-22 |
| `build_projection_handoff.py` | shim | `squadopt.application.projection_handoff`; `docs/weekly_runbook.md` | 2026-10-02 |
| `build_scoreboard.py` | shim | `squadopt.application.scoreboard`; `docs/weekly_runbook.md` | 2026-10-04 |
| `build_settled_site.py` | operational | a scratch GW5 settled candidate through `squadopt.application.settled_publication`, held to the league tree checks of `check_league_tree.py` before it is written; `docs/deployment_runbook.md`, `docs/weekly_runbook.md` | 2026-09-26 |
| `build_site.py` | shim | `squadopt.application.site_publication`; `docs/weekly_runbook.md` | 2026-09-19 |
| `capture_club_news.py` | shim | `squadopt.platform.club_news_acquire`; `docs/weekly_runbook.md` | 2026-09-16 |
| `capture_elite_picks.py` | shim | `squadopt.platform.elite_capture`; `docs/weekly_runbook.md` | 2026-09-10 |
| `capture_official_injuries.py` | shim | `squadopt.platform.official_injury_capture`; `docs/operations/official_injury_discovery.md` | 2026-10-02 |
| `capture_top100_cohort.py` | shim | `squadopt.platform.cohort_capture`; `docs/weekly_runbook.md` | 2026-09-10 |
| `check_football_prospective_inputs.py` | operational | an outcome-free readiness audit of a named offline capture inventory, printed; writes nothing; pairs the current arm by the rule of `docs/football_prospective_pairing_note.md` through `football_prospective_inputs.py`, without the backend; `docs/football_prospective_input_check.md` | 2026-10-14 |
| `check_league_tree.py` | operational | the league tree release checks on a site's data directory or its origin URL; writes nothing; `docs/weekly_runbook.md`, `docs/deployment_runbook.md`; imported by `build_settled_site.py` | 2026-10-11 |
| `export_player_evidence.py` | shim | `squadopt.application.player_evidence`; `docs/weekly_runbook.md` | 2026-09-26 |
| `export_rotation_evidence.py` | shim | `squadopt.application.rotation_export`; `docs/weekly_runbook.md` | 2026-09-26 |
| `export_settled_outcomes.py` | shim | `squadopt.application.settled_outcomes` | 2026-09-26 |
| `fetch_historical_data.py` | operational | `docs/data_pipeline.md`; named by `src/squadopt/data/sources/vaastav.py` and six scripts | 2026-08-14 |
| `moderate_contributions.py` | operational | lists, approves or rejects community contributions in the backend store's `contributions.sqlite3`; `docs/contributions.md` | 2026-09-22 |
| `prepare_football_bundle.py` | operational | seals already produced football inputs with one ready marker under `--artifact-root` (`squadopt.platform.football_bundle`); no fetch, fit or activation; `docs/weekly_runbook.md`, `docs/backend_runbook.md` | 2026-10-04 |
| `publish_gameweek_site.py` | shim | `squadopt.platform.weekly_publish`; `docs/weekly_runbook.md` | 2026-09-10 |
| `recommend_current_squad.py` | operational | `docs/opening_week_runbook.md`, `docs/gw1_run_sheet.md`, `docs/gw2_run_sheet.md` | 2026-09-19 |
| `run_artifact_preflight.py` | operational | `docs/recalibration_runbook.md`; validates, writes nothing by default | 2026-08-15 |
| `run_calendar_recalibration.py` | operational | `docs/recalibration_runbook.md`; `--json-output` only | 2026-08-15 |
| `run_measurement_preflight.py` | operational | validates a `docs/*.json` record; ADR 0003, `docs/measurements_index.md` | 2026-08-16 |
| `run_week.py` | shim | `squadopt.platform.weekly_operations`; `docs/weekly_runbook.md` | 2026-10-12 |
| `seed_entry_registry.py` | operational | `data/entries/registry.json`; `docs/weekly_runbook.md` | 2026-10-04 |
| `smoke_backend_local.py` | operational | `docs/backend_free_hosting.md`; standard library only, writes nothing | 2026-09-26 |

## Release recipe

The owner runs the release from a checkout
([deployment runbook](../docs/deployment_runbook.md)): `ship.sh` waits for the site pull
request to merge, cuts the release and calls `deploy.sh` and `verify_live.py`, and
`restart_backend.ps1` follows it.

| Script | Class | What it does, and what names it | Last commit |
| --- | --- | --- | --- |
| `release/clean_body.py` | release recipe | rewrites a pull request body file in place, dropping attribution lines and replacing long dashes, before the pull request enters the merge queue; `docs/deployment_runbook.md` | 2026-09-19 |
| `release/deploy.sh` | release recipe | refuses unless `main` is a two-parent merge whose tree is `develop`'s; waits for main's push CI and its single `site` artifact, tags, dispatches the Pages workflow and watches the run | 2026-09-26 |
| `release/restart_backend.ps1` | release recipe | verifies the published site, fast-forwards `develop` and restarts the recorded backend; refuses, unless `-Force`, when `develop` differs from the live `site-*` release in `src`, `scripts` or `docs/contracts` | 2026-10-05 |
| `release/vm_football_release.py` | release recipe | after a release, from the PC: packs one week's four data roots and club-news source with a sha256 manifest, unpacks it on the VM as an immutable release, builds the tag's image, renders and seals the football bundle on Linux when the week has one, proves the release on a second Compose project, then switches the live project with a kept rollback; `docs/operations/vm_release_package.md` | 2026-10-22 |
| `vm_push.sh` | release recipe | superseded on the VM's release layout by `release/vm_football_release.py` (it restarts on the previous release's mounts); after a release, from the PC: streams the captures, handoffs and the per-capture artifacts to the backend VM in one tar over SSH, then runs `vm_sync.sh` there; host and key from `SQUADOPT_VM_HOST` and `SQUADOPT_VM_KEY`, no secret inside; `docs/backend_free_hosting.md` | 2026-10-15 |
| `vm_sync.sh` | release recipe | on the VM: checks the release tag out, refreshes the site data the backend reads, rebuilds the image for the tag and restarts the two Compose services, then prints readiness and the capabilities | 2026-10-15 |
| `release/ship.sh` | release recipe | waits for the site pull request, cuts the release to `main` as a two-parent merge whose tree is `develop`'s, then runs `deploy.sh` and `verify_live.py` | 2026-10-04 |
| `release/verify_live.py` | release recipe | checks the live site's routes, documents, assets and content after a deploy; a test holds its route list equal to `web/scripts/smoke-deployment.mjs` | 2026-10-04 |

## Windows backend and data backup

These run on the owner's Windows PC under Windows PowerShell 5.1. Two scheduled tasks, which
the owner registers by hand, hold absolute paths to them: `SquadOptBackendWatch` runs
`start_backend_at_logon.ps1 -Watch` ([backend free hosting](../docs/backend_free_hosting.md)),
and `SquadOptDataBackup` runs `backup_data.ps1` daily
([deployment runbook](../docs/deployment_runbook.md#back-up-irreplaceable-data)). Their paths
do not move.

| Script | Class | What it does, and what names it | Last commit |
| --- | --- | --- | --- |
| `backend_parentage.ps1` | Windows backend | dot-sourced by `run_backend_local.ps1` and `release/restart_backend.ps1`; refuses to start the backend from an agent application's process tree | 2026-10-05 |
| `backup_data.ps1` | Windows backend | additive, checksummed copy of the private `data/` trees to a destination outside every worktree, or `-Verify` of the latest manifest; `docs/deployment_runbook.md` | 2026-10-11 |
| `run_backend_local.ps1` | Windows backend | one API and N workers from the repository's `.venv` over one local store, recorded in `<store>\run\backend.pids.json`; `-Status` and `-Stop`; writes only under git-ignored `data/runtime/backend`; `docs/backend_free_hosting.md` | 2026-10-05 |
| `weekly_run.ps1` | Windows weekly run | one weekly run on this PC as the planner's Start button runs it: reads the open gameweek from the published fixtures document, refuses a dirty checkout, a checkout off `develop` or a run in progress, fast-forwards `develop`, runs the weekly command with the cadence's arguments into `data/logs/weekly/<run id>.log`, and ends with the site pull request, the `ship.sh` line and the VM sync; `-DryRun` prints the plan; `docs/weekly_runbook.md` | 2026-10-15 |
| `weekly_run_friday.ps1` | Windows weekly run | `weekly_run.ps1 -Kind friday`: the decision run, tag `site-<season>-gw<open>-decision` or the next fix tag | 2026-10-15 |
| `weekly_run_tuesday.ps1` | Windows weekly run | `weekly_run.ps1 -Kind tuesday`: the next gameweek's run carrying the settled week, tag `site-<season>-gw<settled>-settled` or the next fix tag | 2026-10-15 |
| `start_backend_at_logon.ps1` | Windows backend | starts whichever of the backend and its Cloudflare Tunnel connector is not running; with `-Watch` it checks every 60 seconds; `docs/backend_free_hosting.md` | 2026-10-05 |

## Measurement runners

| Script | Class | Record it writes, or what names it | Last commit |
| --- | --- | --- | --- |
| `analyze_football_components.py` | measurement runner | one `--output` JSON file it refuses to overwrite, summarizing paired factorial losses; its command is in `docs/research/football_component_ablation.md` | 2026-09-22 |
| `analyze_football_windows.py` | measurement runner | a fresh `--output` directory; `docs/research/football_window_totals.json` records this file's hash | 2026-09-28 |
| `append_weekly_scorecard.py` | measurement runner | `docs/weekly_scorecard.md` (Markdown record) | 2026-08-23 |
| `build_mode_price_list.py` | measurement runner | `docs/mode_price_list.json` | 2026-08-20 |
| `build_projection_horizon.py` | measurement runner | `docs/projection_horizon_run.md` (Markdown record); writes `data/handoffs/` | 2026-09-26 |
| `evaluate_phase_c_components.py` | measurement runner | `docs/phase_c_component_evaluation.json` | 2026-09-21 |
| `export_candidate_residuals.py` | measurement runner | `docs/candidate_residual_export.md` (Markdown record); export in `artifacts/` | 2026-09-26 |
| `export_control_residuals.py` | measurement runner | `docs/control_residual_export.md` (Markdown record); export in `artifacts/` | 2026-09-26 |
| `freeze_candidate_declaration.py` | measurement runner | `docs/issue43_candidate_declaration.json` | 2026-08-19 |
| `measure_anchored_calibration.py` | measurement runner | `docs/anchored_calibration.json` | 2026-09-19 |
| `measure_appearance_recalibration.py` | measurement runner | `docs/appearance_recalibration.json`, `docs/appearance_recalibration.md`, once (it refuses to overwrite them); protocol `docs/appearance_recalibration_prereg.md` | 2026-09-21 |
| `measure_benchmark_v2.py` | measurement runner | `docs/benchmark_v2.json` | 2026-09-01 |
| `measure_calendar_chip.py` | measurement runner | a fresh output directory; `docs/research/calendar_chip_tail.json` records this file's hash | 2026-09-28 |
| `measure_capture_lead_time.py` | measurement runner | `docs/capture_lead_time.json`; also `docs/weekly_runbook.md` | 2026-09-08 |
| `measure_chip_forecast_rule.py` | measurement runner | `docs/chip_forecast_rule.json`, `docs/chip_forecast_rule.md`; protocol `docs/chip_forecast_prereg.md` | 2026-09-19 |
| `measure_chip_threshold_induction.py` | measurement runner | `docs/chip_threshold_induction.json`, `docs/chip_threshold_induction.md`, in two stages; reads `docs/chip_forecast_rule.json`; protocol `docs/chip_threshold_induction_prereg.md` | 2026-09-20 |
| `measure_component_fidelity.py` | measurement runner | `docs/phase_d_component_fidelity.json`; with `--team-match-block` or `--team-match-joint`, a candidate record such as `docs/research/team_match_block_sampler_fidelity.json` or `docs/research/moe_sampler_fidelity.json` | 2026-10-17 |
| `measure_continuation_diagnostic.py` | measurement runner | a fresh `--output` directory; `docs/research/continuation_diagnostic.json` records this file's hash; protocol `docs/research/continuation_diagnostic_protocol.md` | 2026-09-29 |
| `measure_defcon_component.py` | measurement runner | outcome-free identity check; one owner-authorized `docs/research/defcon_component_reading.{json,md}` record under #1000 | 2026-10-11 |
| `measure_double_reduction.py` | measurement runner | `docs/double_reduction.json`, `docs/double_reduction.md` | 2026-09-26 |
| `measure_explicit_lookahead.py` | measurement runner | a fresh output directory; `docs/research/explicit_lookahead_measurement.json` records this file's hash | 2026-10-05 |
| `measure_feed_freshness.py` | measurement runner | `docs/feed_freshness.json`; also `docs/feed_freshness.md` | 2026-10-16 |
| `measure_football_components.py` | measurement runner | a fresh output directory (component losses and search trials); its command is in `docs/research/football_component_ablation.md` | 2026-09-22 |
| `measure_football_contextual.py` | measurement runner | a fresh `--output` directory; the reproduction entry point of `docs/research/football_contextual_development.md` | 2026-09-22 |
| `measure_football_defcon.py` | measurement runner | a fresh `--output` directory; `docs/research/football_defcon_development.json` records this file's hash; scope `docs/research/football_defcon_development_scope.md` | 2026-09-28 |
| `measure_football_minutes.py` | measurement runner | a fresh `--output` directory; `docs/research/football_sequential_minutes.json` records this file's hash | 2026-09-28 |
| `measure_football_planning.py` | measurement runner | a fresh output directory, from the evidence of `measure_football_components.py`; its command is in `docs/research/football_component_ablation.md` | 2026-09-22 |
| `measure_football_role_minutes.py` | measurement runner | a fresh `--output` directory; `docs/research/football_role_reference_2026_10_03.json` and `docs/research/football_role_followups_2026_10_03.json` each record this file's hash | 2026-10-03 |
| `measure_football_shares.py` | measurement runner | `docs/research/football_share_sizing.json`; summary and player-fixture table in `artifacts/` | 2026-10-11 |
| `measure_guarded_lookahead.py` | measurement runner | a fresh output directory; results `docs/research/lookahead_budget_results_2026-09-30.md` and `docs/research/single_seed_lookahead_results_2026-10-01.md`; protocols `docs/research/lookahead_budget_protocol.md` and `docs/research/single_seed_lookahead_protocol.md` | 2026-10-12 |
| `measure_in_season_blend.py` | measurement runner | `docs/in_season_blend_benchmark.json` | 2026-09-26 |
| `measure_incumbent_refinement.py` | measurement runner | runs `measure_temporal_refinement.py` with the certified incumbent comparison into a fresh output directory; `docs/research/incumbent_refinement_measurement.json` arrived with it in #901 | 2026-09-30 |
| `measure_listed_minutes.py` | measurement runner | the `--output` record, committed as `docs/in_season_listed_minutes.json` beside its reading `docs/in_season_listed_minutes.md` | 2026-10-04 |
| `measure_live_price_honesty.py` | measurement runner | `docs/live_price_honesty.json`, `docs/live_price_honesty.md`, regenerated after a settled gameweek; protocol `docs/live_price_honesty_prereg.md` | 2026-09-26 |
| `measure_live_projection_audit.py` | measurement runner | `docs/live_projection_audit.json`, `docs/live_projection_audit.md`, regenerated after each settled gameweek; protocol `docs/live_projection_audit_prereg.md` | 2026-09-19 |
| `measure_mean_reversion_discount.py` | measurement runner | `docs/research/mean_reversion_discount.json`, `docs/research/mean_reversion_discount.md` through `--merge` of per-season artifacts under `artifacts/mean_reversion_discount/`; a pilot writes only there; protocol `docs/research/mean_reversion_discount_prereg.md` | 2026-10-17 |
| `measure_member_plan_determinism.py` | measurement runner | `docs/member_plan_determinism.json`, `docs/member_plan_determinism.md` | 2026-09-20 |
| `measure_member_window_proofs.py` | measurement runner | `docs/member_window_proofs.json`, `docs/member_window_proofs.md` | 2026-09-19 |
| `measure_mode_plan_selection.py` | measurement runner | `docs/mode_plan_selection.json` | 2026-09-19 |
| `measure_observed_rollout.py` | measurement runner | a fresh output directory; `docs/research/observed_rollout_measurement.json` records this file's hash | 2026-09-29 |
| `measure_opening_prior_exposure.py` | measurement runner | `docs/opening_prior_exposure.json` | 2026-08-28 |
| `measure_overlap_calibration.py` | measurement runner | `docs/overlap_calibration.json` | 2026-09-19 |
| `measure_participation_calibration.py` | measurement runner | `docs/participation_calibration.json`, `docs/participation_calibration.md` | 2026-09-16 |
| `measure_participation_composition.py` | measurement runner | `docs/participation_composition.json`, `docs/participation_composition.md`; descriptive, with no protocol | 2026-09-26 |
| `measure_planning_shortlist.py` | measurement runner | a fresh `--output` directory; `docs/research/planning_shortlist.json` records this file's hash | 2026-09-28 |
| `measure_positional_defence.py` | measurement runner | `docs/positional_defence.json`, `docs/positional_defence.md`, once (it refuses to overwrite them); protocol `docs/positional_defence_prereg.md` | 2026-09-26 |
| `measure_prior_minutes_level.py` | measurement runner | `docs/prior_minutes_level.json`, `docs/prior_minutes_level.md`; protocol `docs/prior_minutes_level_prereg.md` | 2026-09-26 |
| `measure_projection_level_audit.py` | measurement runner | `docs/projection_level_audit.json`, `docs/projection_level_audit.md`; protocol `docs/projection_level_audit_prereg.md` | 2026-09-19 |
| `measure_rank_tail_selector_inertness.py` | measurement runner | `docs/rank_tail_selector_inertness.json`, `docs/rank_tail_selector_inertness.md`, a precondition reading for `docs/rank_tail_selector_prereg.md` | 2026-09-19 |
| `measure_rank_conditional_shrinkage.py` | measurement runner | `docs/research/rank_conditional_shrinkage.json`, `docs/research/rank_conditional_shrinkage.md`, once (it refuses to overwrite them); per-fold table in `artifacts/rank_conditional_shrinkage/`; protocol `docs/research/rank_conditional_shrinkage_prereg.md`; `--folds` runs a pilot that writes nowhere under `docs/` | 2026-10-17 |
| `measure_rival_calibration.py` | measurement runner | `docs/rival_calibration.json` | 2026-09-19 |
| `measure_rotation_ceiling.py` | measurement runner | `docs/rotation_oracle_ceiling.json` | 2026-09-26 |
| `measure_scenario_path_dependence.py` | measurement runner | `docs/scenario_path_dependence.json` | 2026-08-19 |
| `measure_shortlist_matrix.py` | measurement runner | a fresh output directory; `docs/research/planning_shortlist_matrix.json` records this file's hash; four other runners import its `audit_plan` | 2026-09-28 |
| `measure_strategy_bench.py` | measurement runner | `docs/strategy_bench.json` | 2026-09-26 |
| `measure_strategy_rule_scale.py` | measurement runner | `docs/strategy_rule_scale.json`, `docs/strategy_rule_scale.md`; with `--checkpoint gw12` or `gw19`, `docs/strategy_rule_scale_gw12.*` or `_gw19.*` and never the earlier records | 2026-10-11 |
| `measure_strategy_screening.py` | measurement runner | `docs/strategy_screening.json` | 2026-09-26 |
| `measure_template_rival.py` | measurement runner | `docs/template_rival_strength.json` (+ per-season variants) | 2026-09-19 |
| `measure_temporal_refinement.py` | measurement runner | a fresh output directory; `docs/research/temporal_refinement_measurement.json` and `docs/research/triple_refinement_measurement.json` each record this file's hash | 2026-09-30 |
| `measure_top100_effect.py` | measurement runner | `docs/top100_effect_gw12` or `docs/top100_effect_gw20` as `.json` and `.md`, each once (none committed yet); protocol `docs/top100_effect_prereg.md`, usage `docs/top100_effect_reader.md` | 2026-09-21 |
| `measure_window_solver_highs.py` | measurement runner | `docs/research/window_solver_highs.json`, `docs/research/window_solver_highs.md` by default (protocol `docs/window_solver_highs_prereg.md`); with `--record-stem window_solver_highs_current`, `docs/research/window_solver_highs_current.json` and `.md` (protocol `docs/research/window_solver_highs_current_prereg.md`); `check` writes only `artifacts/<stem>/` | 2026-10-17 |
| `read_benchmark_v2_live.py` | measurement runner | `docs/benchmark-v2-live-2026-27.json` and its Markdown twin, with the claim `docs/benchmark-v2-live-2026-27.reading` | 2026-10-11 |
| `record_preseason_difficulty.py` | measurement runner | `docs/preseason_fixture_difficulty.json`; also `docs/gw1_run_sheet.md` | 2026-09-19 |
| `redraw_component_calibration_seeds.py` | measurement runner | adds a descriptive seed-sensitivity reading, under one new key, to a copy of `docs/research/moe_sampler.json` written to `--json-output`; the copy is committed as the record | 2026-10-18 |
| `replay_football_planning.py` | measurement runner | a fresh `--output` directory; `docs/research/football_planning_replay.json` records this file's hash | 2026-09-28 |
| `run_candidate_gate.py` | measurement runner | `docs/issue43_candidate_declaration.json` (reads and judges); `docs/candidate_gate_spec.md` | 2026-10-12 |
| `run_component_squad_calibration.py` | measurement runner | `docs/phase_d_component_squad_calibration.json`; with `--team-match-block` or `--team-match-joint`, a candidate record such as `docs/research/team_match_block_sampler.json` or `docs/research/moe_sampler.json` | 2026-10-17 |
| `run_opening_backtest.py` | measurement runner | `docs/opening_backtest.json` | 2026-09-19 |
| `run_opponent_projection_study.py` | measurement runner | `docs/opponent_projection_study.json` | 2026-08-19 |
| `run_planner_horizon_seasons.py` | measurement runner | `docs/planner_horizon_seasons.json` | 2026-09-26 |
| `run_season_chain_seasons.py` | measurement runner | `docs/season_chain.json` (+ variants), `docs/planner_horizon_rolling.json` | 2026-09-19 |
| `run_terminal_value_study.py` | measurement runner | `docs/terminal_value_study.json` | 2026-08-20 |
| `run_transfer_discipline_seasons.py` | measurement runner | `docs/transfer_discipline.json` (+ rolling variants) | 2026-09-19 |
| `score_planner_policy_chain.py` | measurement runner | `docs/research/planner_policy_chain_gw20.json` and `planner_policy_chain_gw38.json` with their markdown twins, each once, from the chain runner's evidence, the receipts posted on the tracking issue (`--receipts`, `--producer-changes`) and the season's outcome captures; needs a clean, non-shallow clone that reaches origin; protocol `docs/research/planner_policy_chain_prereg.md`, rules 2, 3, 6, 13, 14 and 20 to 37 | 2026-10-11 |

## Artifact-only runners

| Script | Class | Record it writes, or what names it | Last commit |
| --- | --- | --- | --- |
| `build_football_shadow.py` | artifact-only runner | `artifacts/shadow/football_team_share_v1/{football,receipts}/<capture>.json`; `docs/football_prospective_shadow_note.md`, #999 | 2026-10-11 |
| `compare_component_oof_development.py` | artifact-only runner | `--output-dir` (`comparison.json`, `comparison.md`) | 2026-09-26 |
| `export_component_oof.py` | artifact-only runner | `artifacts/phase_c/` | 2026-10-12 |
| `score_component_distribution.py` | artifact-only runner | `--output-dir` (`distribution_scoring.json`, `distribution_scoring.md`); the proper-scoring reading of `docs/research/moe_mixture_prereg.md` | 2026-10-17 |
| `export_decided_appearance.py` | artifact-only runner | `artifacts/double_reduction/`; the `--fitted` input of `measure_double_reduction.py` | 2026-09-26 |
| `measure_availability_transitions.py` | artifact-only runner | a fresh `--output` directory the operator names (`record.json`, `summary.md`); refuses the snapshot root and the repository's `data/` and `docs/`; protocol `docs/availability_transitions_prereg.md` | 2026-10-02 |
| `measure_football_lead_reliability.py` | artifact-only runner | a fresh `--output` directory the operator names (`record.json`, `summary.md`, `forecasts.csv`); refuses the archive and the repository's `data/` and `docs/`; protocol `docs/football_lead_reliability_prereg.md` | 2026-10-07 |
| `measure_planner_policy_chain.py` | artifact-only runner | `artifacts/planner_policy_chain/` (receipts, forecast copies, decision records, weekly manifests, `skipped/gwNN.json` skip records, `runner_fix.json`, `runs.log`), each week copied to `--evidence-copy-root` outside the checkout; reads no outcome; protocol `docs/research/planner_policy_chain_prereg.md` | 2026-10-06 |
| `measure_published_difficulty_live.py` | artifact-only runner | private JSON/CSV under ignored `artifacts/`; usage in `docs/research/published_difficulty_live_runner.md`; one reading after settled GW20 | 2026-10-11 |
| `plan_transfer_horizon.py` | artifact-only runner | `data/handoffs/`; `docs/projection_horizon_contract.md` | 2026-08-31 |
| `preview_football_candidate.py` | artifact-only runner | a fresh `--output` directory (`report.json`) from an explicit offline input bundle; usage in `docs/research/football_candidate_development.md` | 2026-09-22 |
| `probe_phase_e_runtime.py` | artifact-only runner | checkpoints via `_phase_e_checkpoints`; prereg `docs/phase_e_candidate_selection_prereg.md` | 2026-09-19 |
| `run_live_calibration.py` | artifact-only runner | `docs/live_calibration_gwNN.json` (none committed yet) | 2026-08-16 |
| `run_opening_prior_backtest.py` | artifact-only runner | `artifacts/opening_prior/`; `docs/data_pipeline.md`, `prediction/config.py` name it | 2026-08-13 |
| `run_phase_e_live_shadow.py` | artifact-only runner | E4 decide entry point; named by nothing | 2026-09-05 |
| `run_phase_e_shadow.py` | artifact-only runner | `--json-output` (internal destination) | 2026-09-07 |
| `run_transfer_horizon_batch.py` | artifact-only runner | `artifacts/live/`; `docs/projection_horizon_contract.md` | 2026-08-31 |

## Fixture and code generators

| Script | Class | Record it writes, or what names it | Last commit |
| --- | --- | --- | --- |
| `export_chip_forecast_fixture.py` | fixture generator | `web/src/fixtures/chip-forecast/cases.json`; #1003 | 2026-10-11 |
| `export_device_plan_fixture.py` | fixture generator | `web/src/fixtures/device-plan/instances.json`: synthetic instances with the server planner's answers, which the device solver's web test must reproduce; `docs/contracts/league_device_plan_v1.md` | 2026-10-11 |
| `export_official_scoring_vectors.py` | fixture generator | `web/src/features/liveScore/officialScoring.vectors.json`; synthetic official finished-week scores for #1008 | 2026-10-11 |
| `export_entry_state_vectors.py` | fixture generator | `web/src/features/league/entryState/vectors.json`; synthetic picks, banking, Free Hit, chip-state and deadline answers for the offline device entry readers (#983) | 2026-10-21 |
| `export_entry_price_vectors.py` | fixture generator | `web/src/features/league/entryState/price-vectors.json`; synthetic purchase-price replay, selling-rule and late-joiner fallback answers (#983) | 2026-10-21 |
| `export_entry_strategy_vectors.py` | fixture generator | `web/src/features/league/entryState/strategy-vectors.json`; synthetic default-rival and accepted strategy-rule answers for every season week (#983) | 2026-10-22 |
| `generate_club_news_coding_fixture.py` | fixture generator | committed coding fixture; `docs/rotation_claim_coding.md` | 2026-09-10 |
| `generate_club_news_fixture.py` | fixture generator | committed club-news fixture | 2026-09-08 |
| `generate_honesty_stems.py` | code generator | `src/squadopt/contracts/honesty_stems.py` from `docs/contracts/honesty_words.json`, so an installed wheel needs no `docs/` folder | 2026-09-19 |
| `generate_sample_data.py` | fixture generator | `data/sample/`; `docs/data_pipeline.md` | 2026-08-11 |

After exporting official scoring vectors, run
`npx prettier --write src/features/liveScore/officialScoring.vectors.json` from
`web`. The drift test compares parsed JSON, preserving the Python answers while
allowing the web formatter's layout.

## Imported helpers

| Script | Class | Record it writes, or what names it | Last commit |
| --- | --- | --- | --- |
| `_highs_native_driver.py` | helper | imported by `measure_window_solver_highs` and run by it as the native HiGHS child (`python -m scripts._highs_native_driver --job --out`, and `--version` for the guard): `highspy` and the standard library only, never OR-Tools, whose `libhighs.so.1` shares the SONAME | 2026-10-17 |
| `_experiment_cli.py` | helper | imported by every runner that `git grep -l "from scripts._experiment_cli import" -- 'scripts/*.py' \| wc -l` counts: provenance metadata, `write_json`, `write_text` | 2026-10-12 |
| `_phase_e_checkpoints.py` | helper | imported by `probe_phase_e_runtime` | 2026-09-07 |
| `_phase_e_development.py` | helper | imported by `probe_phase_e_runtime`, `_phase_e_evaluation` | 2026-09-07 |
| `_phase_e_evaluation.py` | helper | imported by `run_phase_e_shadow` | 2026-09-19 |
| `_phase_e_inputs.py` | helper | imported by the Phase E runners and helpers | 2026-09-07 |
| `_phase_e_live.py` | helper | imported by `probe_phase_e_runtime`, `_phase_e_shadow_live` | 2026-09-07 |
| `_phase_e_shadow_live.py` | helper | imported by `run_phase_e_live_shadow` | 2026-09-07 |
| `football_prospective_inputs.py` | helper | imported by `check_football_prospective_inputs` and the prospective runner `docs/football_prospective_prereg.md` names: the scored capture, the shadow artifact with its receipt, and default 1 of `docs/football_prospective_pairing_note.md`; imports nothing from `squadopt.platform` | 2026-10-14 |
| `_provenance.py` | helper | imported by `_experiment_cli` and by the operational commands that must not load the laboratory: repository root, git revision, `write_json`, `write_text`; standard library only | 2026-10-13 |

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

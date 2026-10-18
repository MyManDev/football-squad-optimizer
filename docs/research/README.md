# Research and evidence

The research arm measures candidate models, policies and planners, and records what it found
whether the result is positive or not. Its code is the laboratory side tree of the package
(`experiments`, `backtest`, `bayesopt`, `recalibration`, `preflight`; see the
[architecture overview](../../ARCHITECTURE.md#3-the-research-arm-and-the-three-tiers)), its
runners live in `scripts/`, and its records are committed under `docs/`.

## Programmes

| Programme | Entry point |
| --- | --- |
| Product and research phases A to H, and where each stands | [Roadmap](../product/roadmap.md) |
| Prediction research programme | [Research agenda](../prediction_research_agenda.md) |
| Phase C gradient-boosting candidate (declaration and comparison method) | [Gradient-boosting method](phase_c_gradient_boosting_method.md) |
| Prospective benchmark of the live decisions (the Phase A exit) | [Benchmark V2 pre-registration](../benchmark_v2_prereg.md) |
| Experimental football model: development, results and the served model | [Implementation and evidence contract](football_candidate_development.md), [results and rejected ablations](football_candidate_results.md), [experimental football model in member advice](../live-football-model.md) |
| Football prospective reading | [Football prospective pre-registration](../football_prospective_prereg.md) |
| The game's forecast as a who-plays input on live weeks (#1004 step 1) | [Appearance game forecast pre-registration](../appearance_game_forecast_prereg.md) |
| Price changes at later deadlines (#1013 step 1a) | [Price change pre-registration](../price_change_prereg.md) |
| Multi-week planning and lookahead | [Planner state and learning](planner_state_and_learning.md), [explicit lookahead measurement](explicit_lookahead_measurement.md), [observed rollout](observed_rollout.md), [temporal refinement](temporal_refinement.md), [incumbent protection](incumbent_protection_design.md), [purchase basis](acquisition_accounting.md) |
| Human decisions over computed alternatives | [Human decision board](human_decision_board.md) |

## Topics

| Topic | Entry point |
| --- | --- |
| Fixture football candidate and observed planning | [Implementation and evidence contract](football_candidate_development.md) |
| Private set-piece duties candidate | [Source, learned allocation, synthetic checks and real-use gates](football_set_piece_duties.md) |
| Private tactical matchup candidate | [Source, model, synthetic checks and real-use gates](football_tactical_matchup_development.md) |
| Private flagged-player participation and minutes candidate | [Learned flagged-player participation and minutes](football_flag_minutes_development.md) |
| Private all-competition workload candidate | [Private all-competition workload and weekly minutes](football_load_minutes_development.md) |
| Private score-state candidate | [Private learned score-state football experiment](football_score_state_development.md) |
| Football candidate development measurements | [Results and rejected ablations](football_candidate_results.md) |
| Private projected club units and replacement quality | [Model and integration boundaries](football_projected_unit_strength.md) |
| Football Manager source and training feasibility | [Sources, schemas and admission gates](football_fm_source_feasibility.md) |
| Registered findings and evidence | [Measurements index](../measurements_index.md) |
| Operational component model | [Component policy](../phase_c_operational_component.md) |
| Operational component and Top-100 composition | [Elite policy](../phase_c_operational_elite_policy.md) |
| Deadline-safe evidence | [Phase B contract](../phase_b_evidence_contract.md) |
| Rotation/news evidence | [Rotation contract](../rotation_evidence_contract.md) |
| Residual exports | [Residual contract](../residual_export_contract.md) |
| How records and larger expansions are stored | [Measurement artifacts](../architecture/decisions/0003-measurement-artifacts.md) |
| October 2026 member web practice review | [Existing capabilities, interface sources and ranked experience choices](web_experience_review_2026_10.md) |

## Pre-registrations

A pre-registration fixes a protocol before its measurement runs, and it is frozen when it
merges. Where it has a status line, that line states the protocol's status on the day it was
frozen and is not updated afterwards; the current state is read from the record that fulfils it
and from that record's row in the [measurements index](../measurements_index.md).
Pre-registrations are at the root of `docs/` (`*_prereg.md`) and in this folder (`*_prereg.md`
and `*_protocol.md`). A new one is linked from this guide (the table below, or the programmes
table for one at the root of `docs/`) or from its row in the measurements index, in the same
pull request: `tests/architecture/test_docs_reachable.py` fails on a document that no link
reaches, and a backticked name is not a link.

| Protocol in this folder | Reading |
| --- | --- |
| [Continuation diagnostic](continuation_diagnostic_protocol.md) | Recorded in [continuation diagnostic](continuation_diagnostic.md) |
| [Certified lookahead budget](lookahead_budget_protocol.md) | Recorded in [results of 2026-09-30](lookahead_budget_results_2026-09-30.md) |
| [Single sequential seed](single_seed_lookahead_protocol.md) | Recorded in [results of 2026-10-01](single_seed_lookahead_results_2026-10-01.md) |
| [Three-week repair](triple_repair_protocol.md) | Recorded in [triple refinement measurement](triple_refinement_measurement.md) |
| [Planner policy chain](planner_policy_chain_prereg.md) | Read after GW20 (interim) and GW38 (final); no record yet |
| [Published fixture difficulty, live](published_difficulty_live_prereg.md) | Runner described in [the live runner](published_difficulty_live_runner.md); no record yet |
| [Available attacking shares](football_available_shares_prereg.md) | No record names it yet |
| [Mean-reversion discount for later plan weeks](mean_reversion_discount_prereg.md) | Recorded in [mean-reversion discount](mean_reversion_discount.md): measured, not certified |
| [HiGHS on the current window model](window_solver_highs_current_prereg.md) | Recorded in [HiGHS on the current window model at GW7](window_solver_highs_current.md): a switch is supported on the server, device verdict carried from #1083 |
| [Team-match block resampler for component scenarios](team_match_block_sampler_prereg.md) | Recorded in [the calibration reading](team_match_block_sampler.md) and [the fidelity diagnostic](team_match_block_sampler_fidelity.md) |
| [Rank-conditional shrinkage of expected points](rank_conditional_shrinkage_prereg.md) | Recorded in [rank-conditional shrinkage](rank_conditional_shrinkage.md): measured, not certified |
| [Joint team-match sampler, zero atom and club block in one draw](moe_sampler_prereg.md) | Recorded in [the calibration reading](moe_sampler.md) and [the fidelity diagnostic](moe_sampler_fidelity.md): `candidate_within_gates` at the frozen seed 0, measured, not certified; not robust across seeds (added after the result) and not a basis for a pin |

## Reproducing a record

1. Find the record's row in the [measurements index](../measurements_index.md), and its runner
   in the [script catalogue](../../scripts/README.md), which names the record each measurement
   runner writes. A runner removed since is listed under "Retired runners" there, with how to
   restore it.
2. Read the commit the record names (`repository_commit`, `producer_repository_commit` or
   `repo_commit`) and check that commit out in a separate worktree. The JSON records that name
   no commit are on two frozen lists in `tests/architecture/test_records_name_their_code.py`,
   one for the root of `docs/` and one for this folder, which holds 19 of the 20 here.
   Some of those name a commit under another key, such as `source_commit` or `base_commit`,
   which may be the code that ran or a base the run changed, so read the record before relying
   on it. For such a record, the commit that added it (`git log --diff-filter=A -- <record>`)
   is the nearest evidence of the code that produced it.
3. Provide the private inputs the record names (captures under `data/`, the historical archive
   under `data/raw/`) and run the runner as `python -m scripts.<name>` with the arguments the
   record or its protocol states.
4. Compare the regenerated record with the committed one. A regenerated record of a kind that
   `squadopt.preflight.measurement.MEASUREMENT_KINDS` names must still pass
   `python -m scripts.run_measurement_preflight`.

A pre-registered gate is read once. Re-running its measurement after the verdict to replace
the record is what pre-registration exists to prevent
([branching](../architecture/branching.md)); a reproduction checks the committed record and
replaces nothing.

Keep implementation, operational selection and measured benefit separate. An available model
or a positive development result does not by itself justify promotion. Preserve chronological
splits, matched populations, negative results and the declared calibration/holdout boundaries.

New research explanations and protocols belong in this folder. Existing machine-readable
records stay at their established paths; moving or regenerating them can change fingerprints
and test fixtures. Inactive or superseded topic branches can be recovered from the preserved
archive using its commit manifest; do not merge the aggregate archive as a research result.

[All documentation](../README.md).

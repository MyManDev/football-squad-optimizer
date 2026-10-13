"""Every document under `docs/` can be reached by following links from the documentation guide.

`docs/README.md` is where a reader starts, and from it the folder guides, the measurements
index and the root guides lead on. A document that no chain of links reaches is found only by
someone who already knows its name. When this test was written, 208 of the 353 Markdown
documents under `docs/` were in that state. In the same change five of them were linked from
the guide of their folder, and the new specifications guide, `docs/specs/README.md`, linked the
eleven root specifications among them. The other 192 are frozen below in two lists that only
shrink.

Reachable means this. Start at `docs/README.md`, follow every relative link of every Markdown
document reached, in `docs/` or anywhere else in the repository (the root guides and the
folder guides are on the way), and repeat. A link is what `test_markdown_links.py` reads as one,
and a link to a folder leads to that folder's `README.md`, as it does on GitHub. A document is
every Markdown file under `docs/` that git lists (tracked, or untracked and not ignored) and
that exists on disk, so a document written but not yet added is checked while its pull request
is being prepared.

The two frozen lists are the unreachable documents of 2026-10-13, split by what would fix them:

- `NAMED_IN_THE_INDEX_WITHOUT_A_LINK`: 119 documents at the root of `docs/` that the
  measurements index names by a backticked name but does not link, among them 84 Markdown twins
  of records and 20 pre-registrations. Turning the name in the index into a link reaches them.
- `NOT_NAMED_IN_THE_INDEX`: the other 73. Each needs a link from the guide its readers use, or
  from the record or document it explains; three are contract notes under `docs/contracts/`,
  whose guide is the place to link them.

A document leaves a list when a link reaches it, and the test fails until it is removed from
the list, so the lists cannot hold a document that is reachable. `LIST_SIZES` pins the size of
each list, so a new document cannot join one without changing a number a reviewer sees.
"""

from __future__ import annotations

import posixpath

from tests.architecture.test_markdown_links import (
    REPOSITORY_ROOT,
    _link_targets,
    _listed_paths,
    _repository_path,
)
from tests.architecture.test_measurements_index import INDEX, _backticked_names

START = "docs/README.md"

#: Unreachable on 2026-10-13, and named by a backticked name in the measurements index.
NAMED_IN_THE_INDEX_WITHOUT_A_LINK: frozenset[str] = frozenset(
    {
        "docs/anchored_calibration.md",
        "docs/appearance_recalibration.md",
        "docs/appearance_recalibration_prereg.md",
        "docs/availability_transitions_prereg.md",
        "docs/baseline_bayesopt.md",
        "docs/baseline_policy_grid.md",
        "docs/benchmark_v2.md",
        "docs/candidate_residual_export.md",
        "docs/candidate_runtime.md",
        "docs/capture_lead_time.md",
        "docs/capture_season_phase.md",
        "docs/chip_bayesopt.md",
        "docs/chip_bayesopt_value.md",
        "docs/chip_bayesopt_wide.md",
        "docs/chip_forecast_rule.md",
        "docs/chip_threshold_induction.md",
        "docs/chip_threshold_induction_prereg.md",
        "docs/control_residual_export.md",
        "docs/control_uncertainty_calibration.md",
        "docs/control_uncertainty_calibration_v2.md",
        "docs/double_reduction.md",
        "docs/export_precision.md",
        "docs/fixture_group_conformal.md",
        "docs/football_lead_reliability_prereg.md",
        "docs/fw10_holdout.md",
        "docs/fw10_holdout_note.md",
        "docs/fw10_holdout_plan.md",
        "docs/fw10_screening.md",
        "docs/fw10_season_robustness.md",
        "docs/horizon_decay.md",
        "docs/in_season_blend_benchmark.md",
        "docs/in_season_listed_minutes.md",
        "docs/in_season_residual_export.md",
        "docs/issue38_calibration_decision.md",
        "docs/issue43_candidate_declaration.md",
        "docs/issue43_handoff_acceptance.md",
        "docs/issue43_stage_a_review.md",
        "docs/learned_benchmark_development.md",
        "docs/live_price_honesty.md",
        "docs/live_price_honesty_prereg.md",
        "docs/live_projection_audit.md",
        "docs/live_projection_audit_prereg.md",
        "docs/measurement_instrument.md",
        "docs/member_plan_determinism.md",
        "docs/member_policy_hit_cost_grid.md",
        "docs/member_window_proofs.md",
        "docs/mode_plan_selection.md",
        "docs/mode_price_list.md",
        "docs/multi_gw_rehearsal.md",
        "docs/opening_newcomer_study.md",
        "docs/opening_prior_exposure.md",
        "docs/opening_prior_exposure_correction.md",
        "docs/opening_two_part.md",
        "docs/opening_two_part_prereg.md",
        "docs/opponent_projection_study.md",
        "docs/opponent_signal.md",
        "docs/overlap_calibration.md",
        "docs/participation_model_prereg.md",
        "docs/phase2_captain_tail_attribution_prereg.md",
        "docs/phase2_shadow_calibration_prereg.md",
        "docs/phase2_tail_diagnostic_prereg.md",
        "docs/phase_c_component_model_prereg.md",
        "docs/phase_c_v2_development_method.md",
        "docs/phase_d_component_fidelity_prereg.md",
        "docs/phase_d_component_squad_calibration_prereg.md",
        "docs/planner_doe.md",
        "docs/planner_horizon_rolling.md",
        "docs/planner_horizon_seasons.md",
        "docs/positional_defence.md",
        "docs/positional_defence_prereg.md",
        "docs/prior_minutes_level.md",
        "docs/prior_minutes_level_prereg.md",
        "docs/production_gate_judgement.md",
        "docs/projection_horizon_run.md",
        "docs/projection_level_audit.md",
        "docs/projection_level_audit_prereg.md",
        "docs/projection_uncertainty_v2_declaration.md",
        "docs/rank_cost_calibration.md",
        "docs/rank_objective_rehearsal.md",
        "docs/rank_proofs.md",
        "docs/rank_tail_selector_inertness.md",
        "docs/rank_tail_selector_prereg.md",
        "docs/recalibration_dry_run.md",
        "docs/residual_signal_scan.md",
        "docs/risk_frontier.md",
        "docs/rival_calibration.md",
        "docs/rotation_evidence_prereg.md",
        "docs/rotation_oracle_ceiling.md",
        "docs/route_a_declaration.md",
        "docs/scenario_bayesopt.md",
        "docs/scenario_bayesopt_deterministic.md",
        "docs/scenario_calibration_audit.md",
        "docs/scenario_path_dependence.md",
        "docs/schedule_signal_study.md",
        "docs/season_chain.md",
        "docs/season_chain_blind.md",
        "docs/season_chain_freehit.md",
        "docs/season_chain_hybrid.md",
        "docs/season_chain_tuned.md",
        "docs/season_chain_value.md",
        "docs/selection_optimism.md",
        "docs/settled_outcomes.md",
        "docs/shrinkage_grid.md",
        "docs/strategy_screening.md",
        "docs/team_rating_cs_remeasure.md",
        "docs/team_rating_study.md",
        "docs/template_rival_strength.md",
        "docs/template_rival_strength_2021-22.md",
        "docs/template_rival_strength_2022-23.md",
        "docs/template_rival_strength_2023-24.md",
        "docs/terminal_value_study.md",
        "docs/time_aware_recalibration.md",
        "docs/transfer_discipline.md",
        "docs/transfer_discipline_blind_rolling.md",
        "docs/transfer_discipline_value_rolling.md",
        "docs/weekly_scorecard.md",
        "docs/window_solver_highs_prereg.md",
        "docs/windowed_rank.md",
        "docs/windowed_rank_note.md",
    }
)

#: Unreachable on 2026-10-13, and named by no backticked name in the measurements index.
NOT_NAMED_IN_THE_INDEX: frozenset[str] = frozenset(
    {
        "docs/anchored_differential_prereg.md",
        "docs/audit_evidence_contract_fixes.md",
        "docs/baseline_benchmark.md",
        "docs/benchmark_v2_live_runner.md",
        "docs/chip_bayesopt_note.md",
        "docs/chip_strategy.md",
        "docs/contracts/football_point_accounting_v1.md",
        "docs/contracts/league_publication_identity_v1.md",
        "docs/contracts/week_live_v1.md",
        "docs/contributions.md",
        "docs/decision_preferences.md",
        "docs/defcon_component_prereg.md",
        "docs/defcon_component_runner.md",
        "docs/expected_lineup_utility.md",
        "docs/fixture_group_conformal_note.md",
        "docs/football_exact_lineup.md",
        "docs/football_match_context.md",
        "docs/football_prospective_pairing_note.md",
        "docs/football_team_form.md",
        "docs/forced_chip_window_prereg.md",
        "docs/gw1_blocker_report_2021-2026.md",
        "docs/gw1_run_sheet.md",
        "docs/gw2_run_sheet.md",
        "docs/handover_2026-08-23.md",
        "docs/live_score_view.md",
        "docs/mode_price_list_prereg.md",
        "docs/opening_backtest.md",
        "docs/opening_newcomer_note.md",
        "docs/opponent_aware_projection_prereg.md",
        "docs/overlap_scaled_edge_prereg.md",
        "docs/phase_c_appearance_control_prereg.md",
        "docs/phase_c_evaluation_prereg.md",
        "docs/phase_d_decision_scoring_prereg.md",
        "docs/phase_d_fixed_decision_readout_prereg.md",
        "docs/phase_d_monte_carlo_v2_prereg.md",
        "docs/phase_d_v2_development_method.md",
        "docs/phase_e_candidate_selection_prereg.md",
        "docs/phase_e_conditional_development_method.md",
        "docs/planner_horizon_rolling_note.md",
        "docs/planner_horizon_seasons_note.md",
        "docs/prediction_ranking_gate.md",
        "docs/rank_cost_calibration_note.md",
        "docs/rank_objective_rehearsal_heldout.md",
        "docs/rank_objective_rehearsal_note.md",
        "docs/recalibration_dry_run_note.md",
        "docs/recalibration_runbook.md",
        "docs/risk_frontier_shrunk.md",
        "docs/rival_edge_prereg.md",
        "docs/rival_scenario_prereg.md",
        "docs/rotation_claim_coding.md",
        "docs/scenario_calibration_audit_dev_dgw.md",
        "docs/scenario_calibration_audit_development.md",
        "docs/scenario_calibration_audit_development_disp.md",
        "docs/scenario_calibration_audit_located_k10.md",
        "docs/scenario_calibration_audit_located_k2.md",
        "docs/scenario_calibration_audit_online.md",
        "docs/scenario_calibration_audit_online_dgw.md",
        "docs/scenario_calibration_audit_online_disp.md",
        "docs/scenario_calibration_audit_shrunk.md",
        "docs/scenario_calibration_correction_note.md",
        "docs/schedule_signal_note.md",
        "docs/season_chain_note.md",
        "docs/strategy_rule_scale_prereg.md",
        "docs/team_rating_cs_prereg.md",
        "docs/team_rating_note.md",
        "docs/terminal_value_note.md",
        "docs/terminal_value_prereg.md",
        "docs/top100_effect_prereg.md",
        "docs/top100_effect_reader.md",
        "docs/transfer_discipline_note.md",
        "docs/transfer_discipline_rolling.md",
        "docs/transfer_scenario_selection_method.md",
        "docs/weekly_suggestion_eval.md",
    }
)

#: The size of each list. Lower it when a document leaves its list; raising it is the growth
#: the lists refuse, so a new unreachable document cannot join one by being added to it.
LIST_SIZES = {"NAMED_IN_THE_INDEX_WITHOUT_A_LINK": 119, "NOT_NAMED_IN_THE_INDEX": 73}


def _documents(listed: list[str]) -> list[str]:
    """Every Markdown file git lists that exists on disk."""

    return [path for path in listed if path.endswith(".md") and (REPOSITORY_ROOT / path).is_file()]


def _links(document: str, markdown: set[str]) -> list[str]:
    """The Markdown documents a document links to, a folder standing for its `README.md`."""

    found: list[str] = []
    text = (REPOSITORY_ROOT / document).read_text(encoding="utf-8")
    for _, raw in _link_targets(text):
        target = _repository_path(document, raw)
        if target is None:
            continue
        if target in markdown:
            found.append(target)
        elif posixpath.join(target, "README.md") in markdown:
            found.append(posixpath.join(target, "README.md"))
    return found


def _reached(start: str, markdown: set[str]) -> set[str]:
    """Every Markdown document a chain of links from `start` reaches, `start` included."""

    reached = {start}
    pending = [start]
    while pending:
        for target in _links(pending.pop(), markdown):
            if target not in reached:
                reached.add(target)
                pending.append(target)
    return reached


def _frozen() -> frozenset[str]:
    return NAMED_IN_THE_INDEX_WITHOUT_A_LINK | NOT_NAMED_IN_THE_INDEX


def _unreachable() -> set[str]:
    markdown = set(_documents(_listed_paths()))
    reached = _reached(START, markdown)
    return {path for path in markdown if path.startswith("docs/") and path not in reached}


def test_every_document_under_docs_is_reachable_from_the_guide() -> None:
    unreachable = sorted(_unreachable() - _frozen())

    assert not unreachable, "\n".join(
        [
            "No chain of links from docs/README.md reaches a document under docs/. Link it from",
            "the guide of its folder, or from the document it explains:",
            *unreachable,
        ]
    )


def test_the_lists_of_unreachable_documents_only_shrink() -> None:
    stale = sorted(_frozen() - _unreachable())

    assert not stale, "\n".join(
        [
            "A document on a frozen list is reachable now, or is gone. Remove it from the list:",
            *stale,
        ]
    )


def test_the_two_lists_keep_their_size() -> None:
    sizes = {
        "NAMED_IN_THE_INDEX_WITHOUT_A_LINK": len(NAMED_IN_THE_INDEX_WITHOUT_A_LINK),
        "NOT_NAMED_IN_THE_INDEX": len(NOT_NAMED_IN_THE_INDEX),
    }

    assert sizes == LIST_SIZES, "the lists only shrink: when a document leaves, lower its size"


def test_the_two_lists_say_what_would_fix_each_document() -> None:
    named = _backticked_names(INDEX.read_text(encoding="utf-8"))

    def stem(path: str) -> str:
        return posixpath.splitext(posixpath.basename(path))[0]

    indexed = NAMED_IN_THE_INDEX_WITHOUT_A_LINK

    assert not indexed & NOT_NAMED_IN_THE_INDEX
    assert sorted(path for path in indexed if stem(path) not in named) == []
    assert sorted(path for path in NOT_NAMED_IN_THE_INDEX if stem(path) in named) == []


def test_the_walk_follows_links_to_documents_and_folders() -> None:
    """The walk is exercised on the real guide, so a walk that stopped early is seen here."""

    markdown = set(_documents(_listed_paths()))
    reached = _reached(START, markdown)

    # The guide links a folder, `contracts/`, and the walk reads it as that folder's guide.
    assert "docs/contracts/README.md" in _links(START, markdown)
    # Reached through the root guides and the folder guides, not only from docs/README.md.
    assert {"ARCHITECTURE.md", "scripts/README.md", "docs/specs/README.md"} <= reached
    # If this ever falls near zero the walk has stopped following links and the test is asleep.
    assert len([path for path in reached if path.startswith("docs/")]) >= 100

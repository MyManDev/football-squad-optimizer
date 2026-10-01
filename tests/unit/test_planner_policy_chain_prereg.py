"""The planner policy chain's protocol states the rules its runner will be held to.

``docs/research/planner_policy_chain_prereg.md`` binds from the moment it merges, so a rule it
states wrongly cannot be corrected later. These tests pin the sentences the runner and the scorer
must honour, and that every function and constant the protocol names exists under that name with
the value the protocol gives it. They check existence and values only, so a later change to how
those functions work does not trip them; the runner's own tests hold the behaviour.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from squadopt.application import advice, lineup_publication, weekly_suggestion_eval
from squadopt.data import atomic
from squadopt.data.sources import fpl_live
from squadopt.evaluation import live_series, promotion, statistics
from squadopt.live import football_artifact, recommendation, rules, transfers
from squadopt.optimization import optimizer as squad_optimizer
from squadopt.planning import guarded, observed, pricing
from squadopt.planning import optimizer as planning_optimizer

REPOSITORY = Path(__file__).resolve().parents[2]
PROTOCOL = REPOSITORY / "docs" / "research" / "planner_policy_chain_prereg.md"


def _protocol() -> str:
    """The protocol's text with every run of whitespace read as one space."""

    return " ".join(PROTOCOL.read_text(encoding="utf-8").split())


@pytest.mark.parametrize(
    "sentence",
    [
        "The protocol is `planner_policy_chain_v1`, for season 2026-27",
        "It binds from the commit that merges it.",
        "Every decision is computed from the runner's merge commit, the frozen source.",
        "is the last `fpl-live` capture, by capture instant, whose own target is g",
        "Two captures at the same latest instant make the week missing.",
        "It is never rebuilt, never borrowed from another capture and never written to.",
        "The decision step reads no archive, no handoff, no member or entry document and no"
        " outcome.",
        "A squad that is not proved OPTIMAL stops the chain before its first decision.",
        "so every purchase lot is known",
        "at twenty deterministic units per forecast week",
        "59 and 99, plus the 1-unit hold probe",
        "Only the first week of each arm's plan is played.",
        "which is never reset",
        "It is never filled from another capture or from a forecast built after the deadline.",
        "It is never retried, given a different budget or replaced by another arm's action.",
        "No sale is invented.",
        "A recomputation that disagrees on any decision is refused, and the first record stands.",
        "is scored by `score_recorded_advice` on `official_autosub_captain_v2`",
        "each paid transfer is charged at the game's 4 points",
        "The planning cost of 8 never enters a realized number.",
        "`gw12` and `gw20`, both interim, and `gw38`, final",
        "No outcome is read between readings.",
        "No interval is printed with fewer than six scored weeks.",
        "fewer than 15 scored weeks gives `insufficient_evidence`",
        "An interim may record only `worse_interim`",
        "No verdict switches anything.",
        "Interim records carry paired differences only",
        "No chain reading may be used to withdraw, change or re-time the football option.",
        "`locked_holdout_accessed: false`",
        "never on a Tuesday or Friday",
    ],
)
def test_the_protocol_states_the_rule_its_runner_is_held_to(sentence: str) -> None:
    assert sentence in _protocol()


@pytest.mark.parametrize(
    ("module", "name"),
    [
        (transfers, "plan_transfer_horizon"),
        (transfers, "plan_transfers"),
        (transfers, "_package_decision"),
        (advice, "solve_window_plan"),
        (planning_optimizer, "optimize_transfer_plan"),
        (planning_optimizer, "PLAN_DETERMINISTIC_TIME_LIMIT"),
        (planning_optimizer, "PLAN_WALL_CEILING_SECONDS"),
        (squad_optimizer, "optimize_squad"),
        (pricing, "sell_price_tenths"),
        (recommendation, "read_inputs"),
        (football_artifact, "read_football_forecast"),
        (rules, "read_season_rules"),
        (lineup_publication, "lineup_fields"),
        (weekly_suggestion_eval, "evaluate_week"),
        (weekly_suggestion_eval, "score_recorded_advice"),
        (fpl_live, "scored_gameweeks"),
        (atomic, "write_document_once"),
        (statistics, "season_aware_moving_block_interval"),
        (promotion, "PromotionPolicy"),
        (live_series, "detectable_effect"),
        (live_series, "DetectionPolicy"),
    ],
)
def test_every_name_the_protocol_cites_exists(module: object, name: str) -> None:
    assert hasattr(module, name), f"{getattr(module, '__name__', module)}.{name}"


def test_the_numbers_the_protocol_states_are_the_codes_numbers() -> None:
    assert advice.WINDOW_DETERMINISTIC_UNITS_PER_WEEK == 20.0
    assert advice.WINDOW_WALL_CEILING_SECONDS == 1800.0
    assert advice.WINDOW_LINEARIZATION_LEVEL == 2
    assert planning_optimizer.PLAN_DETERMINISTIC_TIME_LIMIT == 20.0
    assert planning_optimizer.PLAN_WALL_CEILING_SECONDS == 300.0
    assert weekly_suggestion_eval.RECORDED_ADVICE_SCORING_BASIS == "official_autosub_captain_v2"


def test_the_routes_the_protocol_names_carry_the_versions_it_names() -> None:
    text = _protocol()
    assert "`sequential_certified_window_v1`" in text
    assert "`bounded_observed_window_v1`" in text
    assert observed.OBSERVED_WINDOW_VERSION == "bounded_observed_window_v1"
    assert guarded.GUARDED_PLANNER_VERSION == "sequential_certified_window_v1"

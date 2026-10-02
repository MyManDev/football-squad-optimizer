"""The planner policy chain's protocol states the rules its runner will be held to.

``docs/research/planner_policy_chain_prereg.md`` binds from the moment it merges, so a rule it
states wrongly cannot be corrected later. These tests pin the sentences the runner and the
scorer must honour, check that every function, field and policy the protocol names exists under
that name, and recompute the expectation it declares from the two committed records it cites.
They pin no value of a constant in another owner's module: the runner checks those at its first
run, and its own tests hold the behaviour.
"""

from __future__ import annotations

import ast
import dataclasses
import json
import re
import statistics
from pathlib import Path

import pytest

from squadopt.application import advice, lineup_publication, weekly_suggestion_eval
from squadopt.data import atomic, snapshots
from squadopt.data.sources import fpl_live
from squadopt.evaluation import live_series, promotion
from squadopt.evaluation import statistics as interval_statistics
from squadopt.live import football_artifact, football_observations, recommendation, rules, transfers
from squadopt.optimization import optimizer as squad_optimizer
from squadopt.planning import models, pricing
from squadopt.planning import optimizer as planning_optimizer

REPOSITORY = Path(__file__).resolve().parents[2]
PROTOCOL = REPOSITORY / "docs" / "research" / "planner_policy_chain_prereg.md"
ROLLING = REPOSITORY / "docs" / "transfer_discipline_rolling.json"
WEEKLY = REPOSITORY / "docs" / "transfer_discipline.json"


def _protocol() -> str:
    """The protocol's text with every run of whitespace read as one space."""

    return " ".join(PROTOCOL.read_text(encoding="utf-8").split())


@pytest.mark.parametrize(
    "sentence",
    [
        "The protocol is `planner_policy_chain_v1`, for season 2026-27",
        "It binds from the commit that merges it.",
        "the later of two merges: this document's, and that of the runner",
        "Every decision is computed from the runner's merge commit, the frozen source, and"
        " `served` is the routed planner at that commit, whatever version strings it carries.",
        "The first run refuses unless HEAD is that commit.",
        "the Python version, the operating system and architecture",
        "A change to what an arm does is not a fix: it needs a new protocol.",
        "is the last `fpl-live` capture, by capture instant, whose own target is g",
        "Two captures at the same latest instant make the week missing.",
        "the runner decides gameweek g only after its deadline, refuses an earlier decision, and"
        " decides weeks in order, each once.",
        "Its model version must be one this protocol admits, `football_team_share_v1` or"
        " `football_joint_role_minutes_v1`, and one the reader at the frozen commit accepts",
        "the two are never relabelled as one",
        "Each contrast is also reported for each admitted model version on its own weeks",
        "served under a model version rule 6 does not admit",
        "so this protocol asserts none. Each receipt records them from the artifact itself",
        "A field the artifact does not carry is recorded as absent and never filled in.",
        "The runner reads the file's bytes once, records their sha256",
        "The artifact is never rebuilt, never borrowed from another capture and never written to.",
        "The decision step uses no archive, no handoff, no member or entry payload and nothing"
        " captured after the week's deadline enters a decision.",
        "Later captures are read only for the deadlines they state (rule 5)",
        "never the feature commit that wrote it",
        "before 2026-10-07T00:00:00Z and 2026-10-09T00:00:00Z",
        "No decision is computed before 2026-10-11T10:00:00Z, the end of the 9 to 11 October"
        " freeze",
        "A squad not proved OPTIMAL at 60 units is built once more at 240.",
        "A squad still not proved drops only its own chains",
        "so every purchase lot is known",
        "at twenty deterministic units per forecast week",
        "59 and 99, plus the 1-unit hold probe",
        "and does not separate the horizon from the cap",
        "the runner checks that their plans carry the same configuration and horizon"
        " fingerprints, and refuses a mismatch",
        "`observed_window.status`",
        "`sequential_incumbent.seed_completed`",
        "Truncated weeks are played, so that each state continues, are labelled truncated and"
        " enter neither primary contrast",
        "A contrast therefore scores at most 31 weeks, GW6 to GW36.",
        "Only the first week of each arm's plan is played.",
        "which is never reset",
        "a mismatch stops the run before anything of that week is written",
        "an observed comparison is published FEASIBLE and is not counted as proved",
        "It is never filled from another capture or from a forecast built after the deadline.",
        "has its hold probe stopped by the probe's own 30-second clock before its unit",
        "That week is scored and stays in the pairs, so a failing arm bears what its failure costs",
        "A failed week is never retried, given a different budget or replaced by another arm's"
        " action.",
        "No sale is invented.",
        "A recomputation that disagrees on any decision is refused, and the first record stands.",
        "leaves the week unscored with its reason, never zero, and listed",
        "is scored by `score_recorded_advice` on `official_autosub_captain_v2`",
        "each paid transfer is charged at the game's 4 points",
        "The planning cost of 8 never enters a realized number.",
        "A pair is exactly zero only when both arms played the same fifteen, eleven, bench order,"
        " captain, vice-captain and hits",
        "There are two readings, each taken once, after the named gameweek settles: `gw20`,"
        " interim, and `gw38`, final.",
        "No outcome capture is read between readings.",
        "with no adjustment for there being two",
        "a confidence level of 0.90, 5000 resamples, blocks of 4, deterministic seed 0 and a"
        " minimum mean improvement of 0.5 points a week",
        "No interval is printed with fewer than six scored weeks.",
        "no verdict at fewer than 15 weeks, no verdict at the interim, and one interim reading"
        " only",
        "The interim records no verdict.",
        "The reading dates do not move, so a later start leaves fewer weeks to read.",
        "this document merged by 6 October and the runner by 8 October, each by the end of that"
        " day in UTC",
        "If either misses its date, the first chain week is GW7",
        "an earlier week is never relabelled as the start",
        "A capture taken after every published deadline has closed targets no gameweek and is left"
        " out.",
        "Each week's receipt lists every capture whose own target is that week, with its instant",
        "copied with their modification times kept",
        "Every run appends a line to a run log in the output directory",
        "adds the recompute-and-compare step to the runner",
        "fewer than 15 scored weeks gives `insufficient_evidence`",
        "No verdict switches anything.",
        "it computes none of that protocol's quantities",
        "No chain reading may be used to withdraw, change or re-time the football option.",
        "and a reading taken twice",
        "`locked_holdout_accessed: false`",
        "`forecast_archive_seasons`",
        "never on a Tuesday or Friday",
        "The owner answered on 2026-10-02 (5948324329): the owner runs both on the owner's machine",
        "Another operator or machine needs a new Answer, and silence is not one",
        "allows a second move in a week from two banked free transfers",
        "and `hold` plans under the same policy",
        "(observed, expected, guarded, or neither)",
        "If no chain has started by gameweek 21's deadline, the runner refuses to start one,"
        " nothing is read and the protocol lapses unrun.",
        "is whatever `plan_transfer_horizon` routes to at the frozen commit",
    ],
)
def test_the_protocol_states_the_rule_its_runner_is_held_to(sentence: str) -> None:
    assert sentence in _protocol()


def test_the_rules_are_numbered_once_and_in_order() -> None:
    numbers = [
        int(match)
        for match in re.findall(r"^\s*(\d+)\. ", PROTOCOL.read_text(encoding="utf-8"), re.M)
    ]
    assert numbers == list(range(1, 41))


def test_every_rule_the_protocol_cites_by_number_exists() -> None:
    cited = {int(n) for n in re.findall(r"\brules? (\d+)\b", _protocol())}
    assert cited and cited <= set(range(1, 41))


@pytest.mark.parametrize(
    ("module", "name"),
    [
        (transfers, "plan_transfer_horizon"),
        (transfers, "plan_transfers"),
        (transfers, "_package_decision"),
        (advice, "solve_window_plan"),
        (advice, "WINDOW_DETERMINISTIC_UNITS_PER_WEEK"),
        (advice, "WINDOW_WALL_CEILING_SECONDS"),
        (advice, "WINDOW_LINEARIZATION_LEVEL"),
        (planning_optimizer, "optimize_transfer_plan"),
        (planning_optimizer, "PLAN_DETERMINISTIC_TIME_LIMIT"),
        (planning_optimizer, "PLAN_WALL_CEILING_SECONDS"),
        (squad_optimizer, "optimize_squad"),
        (pricing, "sell_price_tenths"),
        (recommendation, "read_inputs"),
        (snapshots, "read_snapshot"),
        (football_artifact, "read_football_forecast"),
        (football_observations, "availability_observations"),
        (rules, "read_season_rules"),
        (lineup_publication, "lineup_fields"),
        (weekly_suggestion_eval, "evaluate_week"),
        (weekly_suggestion_eval, "score_recorded_advice"),
        (fpl_live, "scored_gameweeks"),
        (atomic, "write_document_once"),
        (interval_statistics, "season_aware_moving_block_interval"),
        (promotion, "PromotionPolicy"),
        (live_series, "detectable_effect"),
        (live_series, "DetectionPolicy"),
    ],
)
def test_every_name_the_protocol_cites_exists(module: object, name: str) -> None:
    assert hasattr(module, name), f"{getattr(module, '__name__', module)}.{name}"


def test_the_week_fields_the_state_carries_exist() -> None:
    fields = {field.name for field in dataclasses.fields(models.PlanningWeekResult)}
    assert {"bank_after_tenths", "free_transfers_for_next_gameweek"} <= fields


def test_the_policies_the_protocol_binds_accept_its_values() -> None:
    policy = promotion.PromotionPolicy(
        min_mean_improvement=0.5,
        confidence_level=0.90,
        bootstrap_resamples=5000,
        moving_block_length=4,
        deterministic_seed=0,
    )
    assert (policy.confidence_level, policy.bootstrap_resamples) == (0.90, 5000)
    detection = live_series.DetectionPolicy(confidence_level=0.90, power=0.80)
    assert (detection.confidence_level, detection.power) == (0.90, 0.80)


def test_the_coverage_check_the_protocol_prints_is_python() -> None:
    blocks = re.findall(r"```python\n(.*?)```", PROTOCOL.read_text(encoding="utf-8"), re.S)
    assert len(blocks) == 1
    code = "\n".join(line[4:] for line in blocks[0].splitlines())
    names = {node.id for node in ast.walk(ast.parse(code)) if isinstance(node, ast.Name)}
    assert {"PromotionPolicy", "season_aware_moving_block_interval"} <= names


def _net_points(path: Path, variant: str) -> dict[tuple[str, int], float]:
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["locked_holdout_accessed"] is False
    return {
        (str(chain["season"]), int(week["gameweek"])): float(week["net_points"])
        for chain in data["chains"]
        if chain["variant"] == variant
        for week in chain["weeks"]
    }


def test_the_declared_expectation_is_the_committed_analogue() -> None:
    window = _net_points(ROLLING, "L3_chips_reserve_hit8_cap1_ftv0")
    weekly = _net_points(WEEKLY, "L1_chips_reserve_hit8_capnone_ftv0")
    assert set(window) == set(weekly)
    keys = sorted(window)
    differences = [window[key] - weekly[key] for key in keys]
    mean = statistics.fmean(differences)
    deviation = statistics.stdev(differences)
    seasons = sorted({season for season, _ in keys})
    numerator = denominator = 0.0
    totals = []
    for season in seasons:
        run = [window[key] - weekly[key] for key in keys if key[0] == season]
        totals.append(sum(run))
        denominator += sum((value - mean) ** 2 for value in run)
        numerator += sum((a - mean) * (b - mean) for a, b in zip(run[1:], run[:-1], strict=True))
    policy = live_series.DetectionPolicy(confidence_level=0.90, power=0.80)
    stated = {
        "Over 147 paired gameweeks": len(keys) == 147,
        f"the mean difference is {mean:+.2f} points a gameweek": round(mean, 2) == 0.97,
        f"a standard deviation of {deviation:.2f}": round(deviation, 2) == 11.60,
        f"a lag-one autocorrelation of {numerator / denominator:.2f}": True,
        "+268, -40, -21 and -64 points by season": [round(t) for t in totals]
        == [268, -40, -21, -64],
        f"is {live_series.detectable_effect(deviation, 15, policy=policy):.2f} points a gameweek"
        " at 15 scored weeks": True,
        f"and {live_series.detectable_effect(deviation, 31, policy=policy):.2f} at 31": True,
    }
    text = _protocol()
    for sentence, holds in stated.items():
        assert holds, sentence
        assert sentence in text, sentence


def test_the_index_entry_names_the_two_readings_and_no_other_gameweek() -> None:
    index = (Path(__file__).resolve().parents[2] / "docs" / "measurements_index.md").read_text(
        encoding="utf-8"
    )
    (entry,) = [line for line in index.splitlines() if "planner_policy_chain_prereg.md" in line]
    assert "GW20" in entry and "GW38" in entry
    assert set(re.findall(r"GW\d+", entry)) == {"GW20", "GW38"}

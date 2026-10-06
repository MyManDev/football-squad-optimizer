"""The lead reliability protocol states rules its cited code can honour.

``docs/football_lead_reliability_prereg.md`` binds from the moment it merges, so a premise
it states wrongly cannot be corrected after the run. Three premises carry its design: the
selected archive never opens 2025-26, origins four weeks apart meet a lead-1 forecast at
only four leads, and the interval's policy values are the ones it states. The tests below
pin those premises in the code and pin that the protocol says them.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pandas as pd
from tests.unit.test_football_history import _history

from squadopt.application.football_live import causal_training
from squadopt.data.sources.football_history import ARCHIVE_SEASONS, archive_history
from squadopt.evaluation.promotion import PromotionPolicy
from squadopt.evaluation.statistics import season_aware_moving_block_interval
from squadopt.live.football_horizon import build_football_horizon
from squadopt.prediction.football import FOOTBALL_MODEL_VERSION, FixtureFootballModel

REPOSITORY = Path(__file__).resolve().parents[2]
PROTOCOL = REPOSITORY / "docs" / "football_lead_reliability_prereg.md"
RUNNER = "scripts/measure_football_lead_reliability.py"
SELECTED = ("2022-23", "2023-24", "2024-25")
MEASURED_ORIGINS = (11, 15, 19, 23, 27, 31)


def _text() -> str:
    return re.sub(r"\s+", " ", PROTOCOL.read_text(encoding="utf-8"))


def _section(heading: str) -> str:
    """One ``## `` section of the protocol, with its line wrapping flattened."""

    text = PROTOCOL.read_text(encoding="utf-8")
    match = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    assert match is not None, f"The protocol has no section {heading!r}."
    return re.sub(r"\s+", " ", match.group(1))


def test_the_selected_archive_never_opens_the_season_the_protocol_excludes(
    tmp_path: Path, monkeypatch
) -> None:
    reads: list[Path] = []
    raw = _history().assign(element=[1, 2], was_home=True, team_h_score=2, team_a_score=0)
    raw["kickoff_time"] = raw.kickoff
    files = {
        "merged_gw.csv": raw,
        "players_raw.csv": pd.DataFrame({"id": [1, 2], "code": [101, 202]}),
        "teams.csv": pd.DataFrame({"id": [11, 22], "code": [3, 7]}),
        "fixtures.csv": pd.DataFrame({"id": [10], "team_h": [11], "team_a": [22]}),
    }

    def read(path, **kwargs):
        reads.append(path)
        return files[path.name].copy()

    monkeypatch.setattr(pd, "read_csv", read)
    archive_history(tmp_path, seasons=SELECTED)

    assert "2025-26" in ARCHIVE_SEASONS and "2025-26" not in SELECTED
    assert len(reads) == 4 * len(SELECTED)
    assert not any("2025-26" in path.parts for path in reads)
    assert 'archive_history(root, seasons=("2022-23", "2023-24", "2024-25"))' in _section(
        "Seasons and origins"
    )


def test_the_first_selected_season_supplies_priors_only() -> None:
    assert ARCHIVE_SEASONS[0] == SELECTED[0] == "2022-23"
    assert "ARCHIVE_SEASONS[0]" in inspect.getsource(causal_training)
    assert "2022-23 supplies priors only" in _section("What has been read")


def test_origins_four_weeks_apart_meet_a_lead_one_forecast_at_four_leads_only() -> None:
    """Why every gameweek from GW11 is a lead-1 origin, and why the protocol says so."""

    meeting = {
        origin_week - origin + 1
        for origin in MEASURED_ORIGINS
        for origin_week in MEASURED_ORIGINS
        if origin <= origin_week <= min(origin + 13, 38)
    }
    assert meeting == {1, 5, 9, 13}

    origins = _section("Seasons and origins")
    assert "only when k is 1, 5, 9 or 13" in origins
    assert "every gameweek from GW11 to GW38 of each season" in origins
    assert "used for lead 1 only" in origins


def test_the_horizon_of_each_measured_origin_is_the_one_the_protocol_states() -> None:
    lengths = {origin: min(origin + 13, 38) - origin + 1 for origin in MEASURED_ORIGINS}
    assert lengths == {11: 14, 15: 14, 19: 14, 23: 14, 27: 12, 31: 8}
    assert "fourteen weeks from GW11 to GW23, twelve from GW27 and eight from GW31" in (
        _section("Seasons and origins")
    )


def test_the_interval_uses_the_policy_values_the_protocol_states() -> None:
    policy = PromotionPolicy()
    assert (
        policy.confidence_level,
        policy.bootstrap_resamples,
        policy.moving_block_length,
        policy.deterministic_seed,
    ) == (0.90, 5000, 4, 0)
    assert "candidate_id" in inspect.signature(season_aware_moving_block_interval).parameters
    quantities = _section("Quantities")
    assert "confidence 0.90, 5000 resamples, blocks of 1, seed 0" in quantities
    assert "fewer than six units in total over the two seasons" in quantities
    assert "no interval, marked thin" in quantities
    assert "ordered by target gameweek" in quantities


def test_the_roster_is_decided_before_the_decision_instant() -> None:
    rule = _section("Decision instant, fit and roster")
    assert "gameweek o - 1 or o - 2 of the same season" in rule
    assert "more than three hours before the decision instant" in rule
    assert "Nothing after the decision instant decides who is in the roster" in rule
    assert "does not use it" in rule


def test_the_names_the_protocol_cites_are_the_code_it_means() -> None:
    text = _text()
    assert FOOTBALL_MODEL_VERSION == "football_team_share_v1"
    for cited in (
        archive_history,
        causal_training,
        build_football_horizon,
        FixtureFootballModel,
        season_aware_moving_block_interval,
    ):
        assert f"`{cited.__name__}`" in text or f"`{cited.__name__}(" in text
    assert "captured_at" in inspect.signature(build_football_horizon).parameters
    for path in re.findall(r"`((?:docs|src|scripts)/[\w/.-]+\.(?:md|py))`", text):
        if path == RUNNER and not (REPOSITORY / path).exists():
            continue  # its own pull request, after this protocol merges
        assert (REPOSITORY / path).is_file(), path


def test_the_protocol_opens_no_unread_season_and_claims_no_confirmation() -> None:
    read = _section("What has been read")
    assert "2025-26 is never opened" in read
    assert "claims no confirmation" in read
    record = _section("Records and runner")
    assert '`seasons_never_opened: ["2025-26"]`' in record
    assert "`locked_holdout_accessed: false`" in record
    assert "never rerun with other settings" in record


def test_the_binding_clauses_of_the_primary_quantity_are_pinned() -> None:
    """Review of 5 October: the clauses a runner is held to, not only the roster phrases."""

    quantities = _section("Quantities")
    for clause in (
        "for the same player and fixture, at lead 1 from the lead-1 origin g",
        "Its paired difference is e_k^2 - e_1^2.",
        "The unit is the target gameweek within a season",
        "The lead's figure is the mean over its units.",
        "`candidate_id` `lead_k` for lead k",
        "one coefficient per position",
        "the ten are chosen per origin, target gameweek and position",
    ):
        assert clause in quantities, clause
    apart = _section("Kept apart")
    assert "do not enter the primary quantity or the secondary quantities" in apart
    assert "with no interval" in apart
    instant = _section("Decision instant, fit and roster")
    assert "less 90 minutes" in instant


def test_the_secondaries_and_the_kept_apart_report_name_their_units() -> None:
    """6 October, before the runner: the readings the runner would otherwise have to choose."""

    quantities = _section("Quantities")
    for clause in (
        "each taken as the figure is: a mean over each unit's player-fixtures, then a mean over"
        " the units. The figure is their difference.",
        "by lead from 1 to 14, over the measured origins' matched forecasts in the lead's units",
        "At lead k from 2 to 14 the units are the primary's: the target gameweeks with at least"
        " one pair at lead k",
        "At lead 1, which has no primary, the units are the measured origins' own gameweeks.",
        "Blank and double gameweeks are excluded at every lead",
        "among the matched forecasts, a tie at the tenth place going to the lower player code",
        "paired player-fixtures in the lead's units; lead 1 has no pair.",
    ):
        assert clause in quantities, clause
    apart = _section("Kept apart")
    assert (
        "by lead from 2 to 14: the number of such target gameweeks with at least one pair at that"
        " lead, the number of pairs, and the mean paired difference e_k^2 - e_1^2 over those pairs"
    ) in apart


def test_the_interval_policy_resamples_the_smallest_lead() -> None:
    """Review of 5 October: with blocks of 4 a season of four units could not resample."""

    policy = PromotionPolicy(
        confidence_level=0.90, bootstrap_resamples=5000, moving_block_length=1, deterministic_seed=0
    )
    units = [("2023-24", float(value)) for value in (1.0, 2.0, 4.0, 8.0)]
    units += [("2024-25", float(value)) for value in (1.0, 3.0, 9.0, 27.0)]
    low, high = season_aware_moving_block_interval(units, policy=policy, candidate_id="lead_13")
    assert low < high
    collapsed = PromotionPolicy(
        confidence_level=0.90, bootstrap_resamples=50, moving_block_length=4, deterministic_seed=0
    )
    low, high = season_aware_moving_block_interval(units, policy=collapsed, candidate_id="lead_13")
    assert low == high


def test_the_motivation_names_the_records_that_read_the_early_leads() -> None:
    why = _section("Why this is written")
    assert "scored v1 at leads 1 to 3 from the same six origins" in why
    assert "`docs/research/football_joint_role_minutes_2026_10_02.md`" in why
    assert "neither goes past lead 3" in why
    read = _section("What has been read")
    assert "scored v1 as its control at GW11, 19, 27 and 35 of it" in read

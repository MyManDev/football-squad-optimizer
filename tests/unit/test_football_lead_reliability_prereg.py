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
    assert "confidence 0.90, 5000 resamples, blocks of 4, seed 0" in quantities
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

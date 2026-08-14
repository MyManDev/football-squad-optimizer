"""Tests for opponent strength estimated from shifted results.

The team-grain rolling is new, so its timing guarantees are tested as carefully as the
player-grain ones: a club's own result must never describe the gameweek it was earned in,
and a window must never span two seasons.
"""

from typing import Any

import pandas as pd
import pytest

from squadopt.data.schema import TEAM_GROUP_COLUMNS
from squadopt.features.config import FeatureConfigurationError
from squadopt.features.strength import (
    OPPONENT_STRENGTH_COLUMNS,
    attach_opponent_strength,
    team_gameweek_points,
    team_strength,
)

SEASON = "2024-25"
TEAM_CODES = pd.DataFrame(
    [
        {"season": SEASON, "name": "Arsenal", "code": 3},
        {"season": SEASON, "name": "Liverpool", "code": 14},
        {"season": "2023-24", "name": "Arsenal", "code": 3},
        {"season": "2023-24", "name": "Liverpool", "code": 14},
    ]
)


def _player(
    *,
    team: str = "Arsenal",
    gameweek: int = 1,
    position: str = "MID",
    points: int = 5,
    player_id: int = 1,
    season: str = SEASON,
    minutes: int = 90,
) -> dict[str, Any]:
    return {
        "season": season,
        "gameweek": gameweek,
        "player_id": player_id,
        "name": f"P{player_id}",
        "team_id": team,
        "position": position,
        "price_tenths": 80,
        "minutes": minutes,
        "total_points": points,
    }


def _fixture_rows(gameweeks: int = 4, *, doubles: tuple[int, ...] = ()) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for gameweek in range(1, gameweeks + 1):
        repeats = 2 if gameweek in doubles else 1
        for index in range(repeats):
            rows.append(
                {
                    "season": SEASON,
                    "gameweek": gameweek,
                    "team_id": 3,
                    "opponent_team_id": 14,
                }
            )
            rows.append(
                {
                    "season": SEASON,
                    "gameweek": gameweek,
                    "team_id": 14,
                    "opponent_team_id": 3,
                }
            )
    return pd.DataFrame(rows)


# --- the team-gameweek aggregate --------------------------------------------


def test_points_are_split_into_attacking_and_defensive_units() -> None:
    panel = pd.DataFrame(
        [
            _player(position="MID", points=6, player_id=1),
            _player(position="FWD", points=4, player_id=2),
            _player(position="DEF", points=7, player_id=3),
            _player(position="GK", points=3, player_id=4),
        ]
    )

    totals = team_gameweek_points(panel, TEAM_CODES)

    assert totals["team_attacking_points"].tolist() == [10.0]
    assert totals["team_defensive_points"].tolist() == [10.0]


def test_the_aggregate_is_keyed_on_the_persistent_code() -> None:
    """So it joins the fixture table without a per-season translation."""

    totals = team_gameweek_points(pd.DataFrame([_player(team="Liverpool")]), TEAM_CODES)

    assert totals["team_id"].tolist() == [14]
    assert tuple(totals.columns[:2]) == TEAM_GROUP_COLUMNS


def test_a_club_the_bridge_does_not_name_is_rejected() -> None:
    with pytest.raises(FeatureConfigurationError, match="does not name"):
        team_gameweek_points(pd.DataFrame([_player(team="Everton")]), TEAM_CODES)


# --- timing -----------------------------------------------------------------


def test_a_clubs_own_gameweek_never_describes_itself() -> None:
    panel = pd.DataFrame(
        [_player(gameweek=1, points=2), _player(gameweek=2, points=50, player_id=2)]
    )

    strength = team_strength(panel, TEAM_CODES, window=3).set_index("gameweek")

    assert pd.isna(strength.loc[1, "attack_strength"])
    assert strength.loc[2, "attack_strength"] == pytest.approx(2.0)


def test_perturbing_a_gameweeks_own_points_leaves_its_strength_unchanged() -> None:
    history = [_player(gameweek=gameweek, points=4) for gameweek in (1, 2, 3)]
    baseline = team_strength(pd.DataFrame(history), TEAM_CODES, window=3).set_index("gameweek")

    tampered = [_player(gameweek=gameweek, points=4) for gameweek in (1, 2)]
    tampered.append(_player(gameweek=3, points=999))
    changed = team_strength(pd.DataFrame(tampered), TEAM_CODES, window=3).set_index("gameweek")

    assert changed.loc[3, "attack_strength"] == baseline.loc[3, "attack_strength"]


def test_a_window_never_spans_two_seasons() -> None:
    """The frozen team key carries `season` for exactly this reason."""

    panel = pd.DataFrame(
        [
            _player(season="2023-24", gameweek=37, points=40),
            _player(season="2023-24", gameweek=38, points=40, player_id=2),
            _player(season=SEASON, gameweek=1, points=1, player_id=3),
            _player(season=SEASON, gameweek=2, points=1, player_id=4),
        ]
    )

    strength = team_strength(panel, TEAM_CODES, window=6).set_index(["season", "gameweek"])

    assert pd.isna(strength.loc[(SEASON, 1), "attack_strength"])
    assert strength.loc[(SEASON, 2), "attack_strength"] == pytest.approx(1.0)


def test_one_clubs_form_does_not_reach_another() -> None:
    panel = pd.DataFrame(
        [
            _player(team="Arsenal", gameweek=1, points=30),
            _player(team="Liverpool", gameweek=1, points=2, player_id=2),
            _player(team="Arsenal", gameweek=2, points=0, player_id=3),
            _player(team="Liverpool", gameweek=2, points=0, player_id=4),
        ]
    )

    strength = team_strength(panel, TEAM_CODES, window=6).set_index(["team_id", "gameweek"])

    assert strength.loc[(3, 2), "attack_strength"] == pytest.approx(30.0)
    assert strength.loc[(14, 2), "attack_strength"] == pytest.approx(2.0)


# --- attaching to the panel -------------------------------------------------


def test_a_player_receives_the_strength_of_the_club_he_faces() -> None:
    panel = pd.DataFrame(
        [
            _player(team="Arsenal", gameweek=1, position="MID", points=1),
            _player(team="Liverpool", gameweek=1, position="DEF", points=20, player_id=2),
            _player(team="Arsenal", gameweek=2, position="MID", points=1, player_id=3),
            _player(team="Liverpool", gameweek=2, position="DEF", points=0, player_id=4),
        ]
    )

    attached = attach_opponent_strength(panel, _fixture_rows(2), TEAM_CODES, window=6).set_index(
        ["team_id", "gameweek"]
    )

    # Arsenal in gameweek 2 faces Liverpool, whose defenders scored 20 in gameweek 1.
    assert attached.loc[("Arsenal", 2), "opponent_defence_strength"] == pytest.approx(20.0)


def test_a_double_gameweek_averages_both_opponents() -> None:
    """At player-gameweek grain there is no single opponent to name."""

    panel = pd.DataFrame(
        [
            _player(team="Arsenal", gameweek=1, points=1),
            _player(team="Liverpool", gameweek=1, position="DEF", points=10, player_id=2),
            _player(team="Arsenal", gameweek=2, points=1, player_id=3),
            _player(team="Liverpool", gameweek=2, position="DEF", points=10, player_id=4),
        ]
    )

    attached = attach_opponent_strength(panel, _fixture_rows(2, doubles=(2,)), TEAM_CODES, window=6)

    row = attached.loc[(attached["team_id"] == "Arsenal") & (attached["gameweek"] == 2)]
    assert row["opponent_defence_strength"].tolist() == [pytest.approx(10.0)]


def test_a_club_with_no_fixture_receives_no_opponent_strength() -> None:
    """There is nobody to be strong or weak, and zero would read as the weakest."""

    panel = pd.DataFrame([_player(gameweek=3)])
    fixtures = _fixture_rows(2)

    attached = attach_opponent_strength(panel, fixtures, TEAM_CODES, window=6)

    assert attached["opponent_defence_strength"].isna().all()


def test_row_count_is_preserved() -> None:
    panel = pd.DataFrame([_player(player_id=index, gameweek=1) for index in range(1, 5)])

    attached = attach_opponent_strength(panel, _fixture_rows(1), TEAM_CODES, window=6)

    assert len(attached) == 4


def test_both_strength_columns_are_attached() -> None:
    attached = attach_opponent_strength(
        pd.DataFrame([_player()]), _fixture_rows(1), TEAM_CODES, window=6
    )

    for column in OPPONENT_STRENGTH_COLUMNS:
        assert column in attached.columns


def test_the_input_panel_is_not_modified() -> None:
    panel = pd.DataFrame([_player()])
    before = panel.copy(deep=True)

    attach_opponent_strength(panel, _fixture_rows(1), TEAM_CODES, window=6)

    assert panel.equals(before)


def test_existing_strength_columns_are_not_silently_overwritten() -> None:
    panel = pd.DataFrame([_player()]).assign(opponent_attack_strength=99.0)

    with pytest.raises(FeatureConfigurationError, match="collide"):
        attach_opponent_strength(panel, _fixture_rows(1), TEAM_CODES, window=6)


def test_row_order_does_not_change_the_result() -> None:
    panel = pd.DataFrame(
        [_player(gameweek=1), _player(gameweek=2, player_id=2), _player(gameweek=3, player_id=3)]
    )

    ordered = team_strength(panel, TEAM_CODES, window=6)
    shuffled = team_strength(
        panel.sort_values("gameweek", ascending=False).reset_index(drop=True),
        TEAM_CODES,
        window=6,
    )

    assert ordered.equals(shuffled)

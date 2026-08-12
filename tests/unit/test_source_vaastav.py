"""Tests for the vaastav archive adapter, using a synthetic stand-in for its layout.

No real data is required and nothing here reaches the network. The fixtures imitate
the archive's shape — including the two situations that make its rows tricky, double
gameweeks and repeated records — so the corrections can be verified exactly.
"""

import csv
from pathlib import Path

import pytest

from squadopt.data.errors import DataSourceError, MissingColumnsError
from squadopt.data.sources import vaastav
from squadopt.data.sources.vaastav import (
    SUPPORTED_SEASONS,
    build_panel,
    collapse_to_player_gameweek,
    drop_non_player_rows,
    load_season,
    load_upcoming_roster,
)

SEASON = SUPPORTED_SEASONS[0]

GAMEWEEK_HEADER = [
    "element",
    "fixture",
    "round",
    "name",
    "team",
    "position",
    "value",
    "minutes",
    "total_points",
    "opponent_team",
    "was_home",
]
ROSTER_HEADER = ["id", "code", "element_type", "team", "now_cost", "web_name"]


def _write(path: Path, header: list[str], rows: list[list[object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def _archive(
    tmp_path: Path,
    gameweek_rows: list[list[object]],
    roster_rows: list[list[object]] | None = None,
    *,
    season: str = SEASON,
) -> Path:
    """Lay out a miniature archive with the directory structure the loader expects."""

    root = tmp_path / "archive"
    _write(root / "data" / season / "gws" / "merged_gw.csv", GAMEWEEK_HEADER, gameweek_rows)
    _write(
        root / "data" / season / "players_raw.csv",
        ROSTER_HEADER,
        roster_rows if roster_rows is not None else _default_roster(),
    )
    return root


def _default_roster() -> list[list[object]]:
    return [
        [1, 900001, 1, 10, 45, "Keeper"],
        [2, 900002, 3, 11, 80, "Mid"],
    ]


def _gameweek_row(
    element: int = 2,
    fixture: int = 1,
    round_: int = 1,
    *,
    position: str = "MID",
    value: int = 80,
    minutes: int = 90,
    points: int = 5,
) -> list[object]:
    return [element, fixture, round_, "Mid", 11, position, value, minutes, points, 7, "True"]


# --- double gameweeks and repeated records ----------------------------------


def test_a_double_gameweek_sums_minutes_and_points(tmp_path: Path) -> None:
    root = _archive(
        tmp_path,
        [
            _gameweek_row(fixture=1, minutes=45, points=2),
            _gameweek_row(fixture=2, minutes=90, points=6),
        ],
    )

    frame = load_season(root, SEASON, shift_price=False)

    assert len(frame) == 1
    assert frame.loc[0, "minutes"] == 135
    assert frame.loc[0, "total_points"] == 8


def test_price_is_taken_once_across_a_double_gameweek(tmp_path: Path) -> None:
    """Price does not move within a gameweek, so summing it would be nonsense."""

    root = _archive(
        tmp_path,
        [_gameweek_row(fixture=1, value=80), _gameweek_row(fixture=2, value=80)],
    )

    frame = load_season(root, SEASON, shift_price=False)

    assert frame.loc[0, "price_tenths"] == 80


def test_text_values_are_summed_numerically_not_concatenated(tmp_path: Path) -> None:
    """Guards a silent corruption: summing text turns 1 and 1 into eleven."""

    root = _archive(
        tmp_path,
        [
            _gameweek_row(fixture=1, minutes=1, points=1),
            _gameweek_row(fixture=2, minutes=1, points=1),
        ],
    )

    frame = load_season(root, SEASON, shift_price=False)

    assert frame.loc[0, "minutes"] == 2
    assert frame.loc[0, "total_points"] == 2


def test_a_triple_gameweek_is_summed(tmp_path: Path) -> None:
    """The rescheduled 2020-21 season really contains three fixtures in one gameweek."""

    root = _archive(
        tmp_path,
        [_gameweek_row(fixture=index, minutes=90, points=3) for index in (1, 2, 3)],
    )

    frame = load_season(root, SEASON, shift_price=False)

    assert frame.loc[0, "minutes"] == 270
    assert frame.loc[0, "total_points"] == 9


def test_repeated_records_for_one_fixture_are_dropped_not_summed(tmp_path: Path) -> None:
    """The archive contains byte-identical rows; summing them would double the player."""

    root = _archive(
        tmp_path,
        [
            _gameweek_row(fixture=1, minutes=90, points=7),
            _gameweek_row(fixture=1, minutes=90, points=7),
        ],
    )

    frame = load_season(root, SEASON, shift_price=False)

    assert len(frame) == 1
    assert frame.loc[0, "minutes"] == 90
    assert frame.loc[0, "total_points"] == 7


def test_repeated_and_genuine_rows_are_distinguished(tmp_path: Path) -> None:
    root = _archive(
        tmp_path,
        [
            _gameweek_row(fixture=1, minutes=90, points=7),
            _gameweek_row(fixture=1, minutes=90, points=7),
            _gameweek_row(fixture=2, minutes=30, points=1),
        ],
    )

    frame = load_season(root, SEASON, shift_price=False)

    assert frame.loc[0, "minutes"] == 120
    assert frame.loc[0, "total_points"] == 8


def test_fixture_level_columns_are_not_carried_to_player_gameweek_grain() -> None:
    """Opponent and home/away have no single value when a gameweek holds two fixtures."""

    assert "opponent_team" not in vaastav.COLUMN_MAP
    assert "was_home" not in vaastav.COLUMN_MAP


# --- non-player rows --------------------------------------------------------


def test_manager_rows_are_excluded(tmp_path: Path) -> None:
    """From 2024-25 the archive carries `AM` rows: one per club, not players."""

    root = _archive(
        tmp_path,
        [_gameweek_row(element=2), _gameweek_row(element=1, position="AM")],
        roster_rows=[[1, 900001, 5, 10, 45, "Boss"], [2, 900002, 3, 11, 80, "Mid"]],
    )

    frame = load_season(root, SEASON, shift_price=False)

    assert set(frame["position"]) == {"MID"}
    assert 900001 not in set(frame["player_id"])


@pytest.mark.parametrize("position", ["GK", "DEF", "MID", "FWD"])
def test_every_squad_eligible_position_is_kept(position: str) -> None:
    import pandas as pd

    frame = pd.DataFrame({"position": [position, "AM"]})

    assert drop_non_player_rows(frame)["position"].tolist() == [position]


# --- cross-season identity --------------------------------------------------


def test_player_identity_uses_the_stable_code_not_the_season_element(tmp_path: Path) -> None:
    """`element` is unique only within a season, so it cannot key a player's history."""

    root = _archive(tmp_path, [_gameweek_row(element=2)])

    frame = load_season(root, SEASON, shift_price=False)

    assert frame.loc[0, "player_id"] == 900002


def test_a_gameweek_row_with_no_roster_entry_is_reported(tmp_path: Path) -> None:
    root = _archive(tmp_path, [_gameweek_row(element=99)])

    with pytest.raises(DataSourceError, match="no roster entry"):
        load_season(root, SEASON)


def test_a_roster_with_duplicate_elements_is_refused(tmp_path: Path) -> None:
    root = _archive(
        tmp_path,
        [_gameweek_row(element=2)],
        roster_rows=[[2, 900002, 3, 11, 80, "Mid"], [2, 900003, 3, 11, 80, "Mid"]],
    )

    with pytest.raises(DataSourceError, match="duplicate element ids"):
        load_season(root, SEASON)


# --- price timing -----------------------------------------------------------


def test_price_is_shifted_by_one_gameweek(tmp_path: Path) -> None:
    """Prefer a stale price over one that may encode the gameweek's own result."""

    root = _archive(
        tmp_path,
        [
            _gameweek_row(round_=1, value=80),
            _gameweek_row(round_=2, value=81),
            _gameweek_row(round_=3, value=83),
        ],
    )

    frame = load_season(root, SEASON).sort_values("gameweek")

    assert frame["price_tenths"].tolist() == [80, 80, 81]


def test_the_opening_gameweek_keeps_its_own_price(tmp_path: Path) -> None:
    """No earlier price exists, and this is the gameweek folds already exclude."""

    root = _archive(tmp_path, [_gameweek_row(round_=1, value=80)])

    frame = load_season(root, SEASON)

    assert frame.loc[0, "price_tenths"] == 80


def test_the_shift_can_be_disabled(tmp_path: Path) -> None:
    root = _archive(
        tmp_path,
        [_gameweek_row(round_=1, value=80), _gameweek_row(round_=2, value=81)],
    )

    frame = load_season(root, SEASON, shift_price=False).sort_values("gameweek")

    assert frame["price_tenths"].tolist() == [80, 81]


def test_the_shift_does_not_cross_players(tmp_path: Path) -> None:
    root = _archive(
        tmp_path,
        [
            _gameweek_row(element=1, round_=1, position="GK", value=45),
            _gameweek_row(element=2, round_=1, value=80),
            _gameweek_row(element=2, round_=2, value=90),
        ],
    )

    frame = load_season(root, SEASON).sort_values(["player_id", "gameweek"])
    keeper = frame.loc[frame["player_id"] == 900001, "price_tenths"].tolist()

    assert keeper == [45]


# --- guards -----------------------------------------------------------------


def test_a_season_outside_the_supported_range_is_refused(tmp_path: Path) -> None:
    root = _archive(tmp_path, [_gameweek_row()])

    with pytest.raises(DataSourceError, match="outside the supported range"):
        build_panel(root, seasons=["2016-17"])


def test_older_seasons_are_excluded_because_they_lack_position_and_team() -> None:
    assert "2016-17" not in SUPPORTED_SEASONS
    assert "2018-19" not in SUPPORTED_SEASONS
    assert SUPPORTED_SEASONS[0] == "2020-21"
    assert len(SUPPORTED_SEASONS) == 6


def test_a_missing_file_points_at_the_fetch_script(tmp_path: Path) -> None:
    with pytest.raises(DataSourceError, match="fetch_historical_data"):
        load_season(tmp_path / "nothing-here", SEASON)


def test_a_changed_archive_layout_names_the_pinned_commit(tmp_path: Path) -> None:
    root = tmp_path / "archive"
    _write(
        root / "data" / SEASON / "gws" / "merged_gw.csv",
        ["element", "round"],
        [[2, 1]],
    )
    _write(root / "data" / SEASON / "players_raw.csv", ROSTER_HEADER, _default_roster())

    with pytest.raises(MissingColumnsError, match=vaastav.ARCHIVE_COMMIT):
        load_season(root, SEASON)


def test_an_empty_season_request_is_refused(tmp_path: Path) -> None:
    with pytest.raises(DataSourceError, match="At least one season"):
        build_panel(_archive(tmp_path, [_gameweek_row()]), seasons=[])


def test_the_upcoming_roster_exposes_the_pool_and_opening_prices(tmp_path: Path) -> None:
    """A season with no completed gameweeks still has an unambiguous starting price."""

    root = _archive(tmp_path, [_gameweek_row()])

    roster = load_upcoming_roster(root, SEASON)

    assert list(roster.columns) == ["code", "web_name", "team", "now_cost", "position"]
    assert len(roster) == 2


def test_the_upcoming_roster_translates_numeric_position_codes(tmp_path: Path) -> None:
    """A platform's encoding is source knowledge, so it is resolved here."""

    root = _archive(tmp_path, [_gameweek_row()])

    # The loader reads text by design, so codes arrive as strings; canonical typing
    # happens later, in the projection layer.
    roster = load_upcoming_roster(root, SEASON).set_index("code")

    assert roster.loc["900001", "position"] == "GK"
    assert roster.loc["900002", "position"] == "MID"


def test_the_upcoming_roster_drops_non_player_entries(tmp_path: Path) -> None:
    """Element type 5 is a manager, not a squad-eligible player."""

    root = _archive(
        tmp_path,
        [_gameweek_row()],
        roster_rows=[
            [1, 900001, 1, 10, 45, "Keeper"],
            [2, 900002, 3, 11, 80, "Mid"],
            [3, 900003, 5, 12, 15, "Boss"],
        ],
    )

    roster = load_upcoming_roster(root, SEASON)

    # Compared as text, because an integer would never match and the assertion
    # would pass without testing anything.
    assert set(roster["code"]) == {"900001", "900002"}
    assert len(roster) == 2


def test_collapse_is_idempotent_on_already_unique_rows() -> None:
    import pandas as pd

    frame = pd.DataFrame(
        {
            "element": [1, 2],
            "fixture": [1, 1],
            "round": [1, 1],
            "minutes": [90, 45],
            "total_points": [3, 1],
            "value": [50, 60],
        }
    )

    collapsed = collapse_to_player_gameweek(frame)

    assert collapsed["minutes"].tolist() == [90, 45]
    assert "fixture" not in collapsed.columns

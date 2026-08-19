"""Tests for reading the archive's fixture and team files.

Each test lays out a miniature archive on disk. Nothing here reads real data.
"""

import csv
from pathlib import Path
from typing import Any

import pytest

from squadopt.data.errors import (
    DataSourceError,
    DuplicateRecordsError,
    MissingColumnsError,
)
from squadopt.data.sources.vaastav import (
    ARCHIVE_SNAPSHOT_ID,
    build_fixture_panel,
    load_fixture_snapshot,
    load_team_codes,
)

SEASON = "2025-26"

TEAMS_HEADER = ["id", "code", "name", "short_name"]
FIXTURES_HEADER = [
    "id",
    "event",
    "team_h",
    "team_a",
    "team_h_difficulty",
    "team_a_difficulty",
    "kickoff_time",
    "finished",
    "provisional_start_time",
]

# Per-season id 1 maps to persistent code 3, and id 2 to code 14. The two spaces are
# deliberately different so a test cannot pass by confusing them.
DEFAULT_TEAMS: list[list[Any]] = [
    [1, 3, "Arsenal", "ARS"],
    [2, 14, "Liverpool", "LIV"],
    [3, 43, "Man City", "MCI"],
]


def _write(path: Path, header: list[str], rows: list[list[Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def _fixture_row(
    identifier: int = 1,
    event: Any = 1,
    *,
    home: int = 1,
    away: int = 2,
    home_difficulty: Any = 2,
    away_difficulty: Any = 5,
    kickoff: str = "2025-08-15T19:00:00Z",
    finished: Any = "True",
    provisional: Any = "False",
) -> list[Any]:
    return [
        identifier,
        event,
        home,
        away,
        home_difficulty,
        away_difficulty,
        kickoff,
        finished,
        provisional,
    ]


def _archive(
    tmp_path: Path,
    fixtures: list[list[Any]] | None = None,
    teams: list[list[Any]] | None = None,
    *,
    season: str = SEASON,
) -> Path:
    root = tmp_path / "archive"
    _write(
        root / "data" / season / "fixtures.csv",
        FIXTURES_HEADER,
        [_fixture_row()] if fixtures is None else fixtures,
    )
    _write(
        root / "data" / season / "teams.csv",
        TEAMS_HEADER,
        DEFAULT_TEAMS if teams is None else teams,
    )
    return root


# --- identity ---------------------------------------------------------------


def test_team_identity_is_the_persistent_code_not_the_per_season_id(tmp_path: Path) -> None:
    """The per-season integer denotes different clubs in different seasons."""

    frame = load_fixture_snapshot(_archive(tmp_path), SEASON)

    assert sorted(frame["team_id"].tolist()) == [3, 14]
    assert sorted(frame["opponent_team_id"].tolist()) == [3, 14]


def test_team_codes_expose_all_three_identifiers(tmp_path: Path) -> None:
    teams = load_team_codes(_archive(tmp_path), SEASON)

    assert teams.loc[teams["id"] == 1, "code"].tolist() == [3]
    assert teams.loc[teams["id"] == 1, "name"].tolist() == ["Arsenal"]


def test_a_repeated_team_id_is_rejected(tmp_path: Path) -> None:
    teams = [*DEFAULT_TEAMS, [1, 99, "Arsenal Reserves", "ARR"]]

    with pytest.raises(DuplicateRecordsError, match="repeats team id"):
        load_team_codes(_archive(tmp_path, teams=teams), SEASON)


def test_a_fixture_on_an_undeclared_team_is_rejected(tmp_path: Path) -> None:
    root = _archive(tmp_path, [_fixture_row(home=1, away=99)])

    with pytest.raises(DataSourceError, match="does not declare"):
        load_fixture_snapshot(root, SEASON)


# --- shape ------------------------------------------------------------------


def test_each_fixture_becomes_one_row_per_team(tmp_path: Path) -> None:
    frame = load_fixture_snapshot(_archive(tmp_path), SEASON)

    assert len(frame) == 2
    assert frame["is_home"].tolist() == [True, False] or frame["is_home"].tolist() == [
        False,
        True,
    ]


def test_each_side_carries_the_difficulty_it_faces(tmp_path: Path) -> None:
    root = _archive(tmp_path, [_fixture_row(home_difficulty=2, away_difficulty=5)])

    frame = load_fixture_snapshot(root, SEASON)

    home = frame.loc[frame["is_home"].astype("boolean").fillna(False)].iloc[0]
    away = frame.loc[~frame["is_home"].astype("boolean").fillna(True)].iloc[0]
    assert home["fixture_difficulty"] == 2
    assert away["fixture_difficulty"] == 5


def test_a_double_gameweek_produces_two_fixtures_for_one_club(tmp_path: Path) -> None:
    root = _archive(
        tmp_path,
        [
            _fixture_row(1, event=9, home=1, away=2),
            _fixture_row(2, event=9, home=3, away=1),
        ],
    )

    frame = load_fixture_snapshot(root, SEASON)

    arsenal = frame.loc[(frame["team_id"] == 3) & (frame["gameweek"] == 9)]
    assert len(arsenal) == 2
    assert sorted(arsenal["is_home"].tolist()) == [False, True]


# --- provenance -------------------------------------------------------------


def test_backfilled_rows_name_the_pin_and_leave_live_fields_empty(tmp_path: Path) -> None:
    """The archive publishes neither a capture time nor a deadline."""

    frame = load_fixture_snapshot(_archive(tmp_path), SEASON)

    assert frame["snapshot_id"].unique().tolist() == [ARCHIVE_SNAPSHOT_ID]
    assert frame["captured_at_utc"].isna().all()
    assert frame["deadline_timestamp_utc"].isna().all()


# --- status -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("finished", "provisional", "expected"),
    [
        ("True", "False", "final"),
        ("False", "True", "provisional"),
        ("False", "False", "scheduled"),
        (True, False, "final"),
        (False, False, "scheduled"),
    ],
)
def test_status_is_derived_from_the_published_flags(
    tmp_path: Path, finished: Any, provisional: Any, expected: str
) -> None:
    root = _archive(tmp_path, [_fixture_row(finished=finished, provisional=provisional)])

    frame = load_fixture_snapshot(root, SEASON)

    assert frame["status"].unique().tolist() == [expected]


def test_an_unreadable_flag_stops_the_run(tmp_path: Path) -> None:
    """bool("False") is True, so a text flag must never be coerced by bool()."""

    root = _archive(tmp_path, [_fixture_row(finished="maybe")])

    with pytest.raises(DataSourceError, match="must be a boolean flag"):
        load_fixture_snapshot(root, SEASON)


# --- unscheduled fixtures ---------------------------------------------------


def test_a_fixture_without_a_gameweek_is_excluded(tmp_path: Path) -> None:
    """That is how a postponement awaiting refixturing appears at the source."""

    root = _archive(
        tmp_path,
        [_fixture_row(1, event=1), _fixture_row(2, event="", home=1, away=3)],
    )

    frame = load_fixture_snapshot(root, SEASON)

    assert frame["fixture_id"].unique().tolist() == [1]


def test_a_season_of_only_unscheduled_fixtures_is_an_error(tmp_path: Path) -> None:
    root = _archive(tmp_path, [_fixture_row(1, event="")])

    with pytest.raises(DataSourceError, match="no fixture rows"):
        load_fixture_snapshot(root, SEASON)


# --- timestamps -------------------------------------------------------------


def test_a_kickoff_without_a_timezone_is_rejected(tmp_path: Path) -> None:
    root = _archive(tmp_path, [_fixture_row(kickoff="2025-08-15T19:00:00")])

    with pytest.raises(DataSourceError, match="must state a timezone"):
        load_fixture_snapshot(root, SEASON)


# --- missing files ----------------------------------------------------------


def test_a_missing_teams_file_points_at_the_fetch_command(tmp_path: Path) -> None:
    root = tmp_path / "archive"
    _write(root / "data" / SEASON / "fixtures.csv", FIXTURES_HEADER, [_fixture_row()])

    with pytest.raises(DataSourceError, match="fetch_historical_data"):
        load_fixture_snapshot(root, SEASON)


def test_a_missing_fixture_column_is_reported(tmp_path: Path) -> None:
    root = _archive(tmp_path)
    _write(
        root / "data" / SEASON / "fixtures.csv",
        [name for name in FIXTURES_HEADER if name != "kickoff_time"],
        [[1, 1, 1, 2, 2, 5, "True", "False"]],
    )

    with pytest.raises(MissingColumnsError):
        load_fixture_snapshot(root, SEASON)


# --- multi-season -----------------------------------------------------------


def test_an_unsupported_season_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(DataSourceError, match="outside the supported range"):
        build_fixture_panel(_archive(tmp_path), seasons=["2019-20"])


def test_no_seasons_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(DataSourceError, match="At least one season"):
        build_fixture_panel(_archive(tmp_path), seasons=[])


def test_two_seasons_concatenate_into_one_table(tmp_path: Path) -> None:
    root = _archive(tmp_path, season="2024-25")
    _write(root / "data" / SEASON / "fixtures.csv", FIXTURES_HEADER, [_fixture_row()])
    _write(root / "data" / SEASON / "teams.csv", TEAMS_HEADER, DEFAULT_TEAMS)

    frame = build_fixture_panel(root, seasons=["2024-25", SEASON])

    assert sorted(frame["season"].unique().tolist()) == ["2024-25", "2025-26"]
    assert len(frame) == 4

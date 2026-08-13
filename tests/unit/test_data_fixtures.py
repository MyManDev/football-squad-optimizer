"""Tests for the fixture-level table contract.

Rows are hand-built so every rule can be violated deliberately. Nothing here reads the
archive or the network.
"""

from typing import Any

import pandas as pd
import pytest

from squadopt.data.errors import (
    DuplicateRecordsError,
    InvalidValueError,
    MissingColumnsError,
)
from squadopt.data.fixtures import validate_fixture_snapshot
from squadopt.data.schema import FIXTURE_COLUMNS, FIXTURE_SORT_COLUMNS

SNAPSHOT = "vaastav-8c97b2a"
SEASON = "2025-26"


def _pair(
    fixture_id: int = 1,
    *,
    gameweek: int = 1,
    home: int = 3,
    away: int = 14,
    kickoff: str = "2025-08-15T19:00:00Z",
    status: str = "final",
    snapshot_id: str = SNAPSHOT,
    season: str = SEASON,
) -> list[dict[str, Any]]:
    """Return both sides of one fixture."""

    shared: dict[str, Any] = {
        "snapshot_id": snapshot_id,
        "captured_at_utc": pd.NA,
        "season": season,
        "gameweek": gameweek,
        "fixture_id": fixture_id,
        "kickoff_time_utc": kickoff,
        "deadline_timestamp_utc": pd.NA,
        "status": status,
    }
    return [
        {
            **shared,
            "team_id": home,
            "opponent_team_id": away,
            "is_home": True,
            "fixture_difficulty": 3,
        },
        {
            **shared,
            "team_id": away,
            "opponent_team_id": home,
            "is_home": False,
            "fixture_difficulty": 4,
        },
    ]


def _frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=list(FIXTURE_COLUMNS))
    for column in ("gameweek", "fixture_id", "team_id", "opponent_team_id"):
        frame[column] = frame[column].astype("int64")
    frame["is_home"] = frame["is_home"].astype("boolean")
    frame["fixture_difficulty"] = frame["fixture_difficulty"].astype("Int64")
    for column in (
        "snapshot_id",
        "season",
        "kickoff_time_utc",
        "status",
        "captured_at_utc",
        "deadline_timestamp_utc",
    ):
        frame[column] = frame[column].astype("string")
    return frame


# --- shape and ordering -----------------------------------------------------


def test_a_valid_pair_round_trips() -> None:
    validated = validate_fixture_snapshot(_frame(_pair()))

    assert len(validated) == 2
    assert tuple(validated.columns) == FIXTURE_COLUMNS


def test_rows_come_back_in_canonical_order() -> None:
    rows = _pair(2, gameweek=3) + _pair(1, gameweek=1)

    validated = validate_fixture_snapshot(_frame(rows))

    expected = validated.sort_values(list(FIXTURE_SORT_COLUMNS), kind="stable")
    assert validated.equals(expected.reset_index(drop=True))


def test_the_input_frame_is_not_modified() -> None:
    frame = _frame(_pair())
    before = frame.copy(deep=True)

    validate_fixture_snapshot(frame)

    assert frame.equals(before)


def test_a_double_gameweek_is_representable() -> None:
    """This is the case that made a fixture-level grain necessary."""

    rows = _pair(1, gameweek=9, home=3, away=14) + _pair(2, gameweek=9, home=3, away=8)

    validated = validate_fixture_snapshot(_frame(rows))

    home_rows = validated.loc[(validated["team_id"] == 3) & (validated["gameweek"] == 9)]
    assert len(home_rows) == 2


# --- provenance -------------------------------------------------------------


def test_archive_rows_may_omit_capture_time_and_deadline() -> None:
    """The archive publishes neither, and inventing them would forge provenance."""

    validated = validate_fixture_snapshot(_frame(_pair()))

    assert validated["captured_at_utc"].isna().all()
    assert validated["deadline_timestamp_utc"].isna().all()


def test_a_missing_difficulty_is_accepted_as_source_specific() -> None:
    rows = _pair()
    for row in rows:
        row["fixture_difficulty"] = pd.NA

    validated = validate_fixture_snapshot(_frame(rows))

    assert validated["fixture_difficulty"].isna().all()


@pytest.mark.parametrize("column", ["season", "kickoff_time_utc", "status", "snapshot_id"])
def test_a_non_nullable_column_may_not_be_empty(column: str) -> None:
    rows = _pair()
    rows[0][column] = pd.NA

    with pytest.raises(InvalidValueError, match=f"{column!r} may not be empty"):
        validate_fixture_snapshot(_frame(rows))


# --- keys and identity ------------------------------------------------------


def test_a_repeated_key_is_rejected() -> None:
    rows = _pair() + _pair()

    with pytest.raises(DuplicateRecordsError, match="must be unique"):
        validate_fixture_snapshot(_frame(rows))


def test_the_same_fixture_in_two_snapshots_is_not_a_duplicate() -> None:
    """Two captures of one season describe the same fixture at different times."""

    rows = _pair() + _pair(snapshot_id="fpl-live-20260101T000000Z-abcabcabcabc")

    validated = validate_fixture_snapshot(_frame(rows))

    assert len(validated) == 4


def test_a_club_cannot_play_itself() -> None:
    rows = _pair()
    rows[0]["opponent_team_id"] = rows[0]["team_id"]
    rows[1]["team_id"] = rows[1]["opponent_team_id"]

    with pytest.raises(InvalidValueError, match="same club as team and opponent"):
        validate_fixture_snapshot(_frame(rows))


def test_a_nullable_integer_identifier_is_rejected() -> None:
    """A missing identifier would survive into a join and match nothing."""

    frame = _frame(_pair())
    frame["team_id"] = frame["team_id"].astype("Int64")

    with pytest.raises(InvalidValueError, match="must be a non-nullable integer dtype"):
        validate_fixture_snapshot(frame)


# --- mutual consistency of the two sides ------------------------------------


def test_a_fixture_stored_only_once_is_rejected() -> None:
    with pytest.raises(InvalidValueError, match="exactly two rows describe it"):
        validate_fixture_snapshot(_frame(_pair()[:1]))


def test_two_home_rows_are_rejected() -> None:
    rows = _pair()
    rows[1]["is_home"] = True

    with pytest.raises(InvalidValueError, match="exactly one home row"):
        validate_fixture_snapshot(_frame(rows))


def test_sides_that_do_not_mirror_each_other_are_rejected() -> None:
    """One side's feature would otherwise contradict the same feature from the other."""

    rows = _pair(home=3, away=14)
    rows[1]["opponent_team_id"] = 99

    with pytest.raises(InvalidValueError, match="do not mirror each other"):
        validate_fixture_snapshot(_frame(rows))


@pytest.mark.parametrize(
    ("column", "value"),
    [("gameweek", 2), ("kickoff_time_utc", "2025-08-16T19:00:00Z"), ("status", "scheduled")],
)
def test_sides_disagreeing_on_shared_detail_are_rejected(column: str, value: object) -> None:
    rows = _pair()
    rows[1][column] = value

    with pytest.raises(InvalidValueError, match=f"disagrees on {column!r}"):
        validate_fixture_snapshot(_frame(rows))


# --- values -----------------------------------------------------------------


def test_an_unknown_status_is_rejected() -> None:
    rows = _pair(status="postponed")

    with pytest.raises(InvalidValueError, match="status must be one of"):
        validate_fixture_snapshot(_frame(rows))


def test_a_non_positive_gameweek_is_rejected() -> None:
    rows = _pair(gameweek=0)

    with pytest.raises(InvalidValueError, match="at least 1"):
        validate_fixture_snapshot(_frame(rows))


def test_a_local_time_kickoff_is_rejected() -> None:
    rows = _pair(kickoff="2025-08-15T20:00:00+01:00")

    with pytest.raises(Exception, match="must be expressed in UTC"):
        validate_fixture_snapshot(_frame(rows))


# --- table shape ------------------------------------------------------------


def test_a_missing_column_names_what_was_there() -> None:
    frame = _frame(_pair()).drop(columns=["status"])

    with pytest.raises(MissingColumnsError, match="missing columns"):
        validate_fixture_snapshot(frame)


def test_an_extra_column_is_rejected() -> None:
    """A derived quantity belongs in the aggregation step, not the stored table."""

    frame = _frame(_pair())
    frame["mean_fixture_difficulty"] = 3.5

    with pytest.raises(InvalidValueError, match="does not define"):
        validate_fixture_snapshot(frame)


def test_an_empty_table_is_rejected() -> None:
    with pytest.raises(InvalidValueError, match="no rows"):
        validate_fixture_snapshot(_frame([]))


def test_a_non_frame_is_rejected() -> None:
    with pytest.raises(InvalidValueError, match="must be a pandas DataFrame"):
        validate_fixture_snapshot([1, 2])  # type: ignore[arg-type]

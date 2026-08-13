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
from squadopt.data.fixtures import (
    aggregate_team_gameweek,
    blank_gameweek_defaults,
    validate_fixture_snapshot,
)
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


@pytest.mark.parametrize("column", ["season", "status", "snapshot_id"])
def test_a_non_nullable_column_may_not_be_empty(column: str) -> None:
    rows = _pair()
    rows[0][column] = pd.NA

    with pytest.raises(InvalidValueError, match=f"{column!r} may not be empty"):
        validate_fixture_snapshot(_frame(rows))


def test_a_fixture_awaiting_a_kickoff_time_is_accepted() -> None:
    """A gameweek can be assigned before the time is confirmed, and no feature reads it."""

    rows = _pair()
    for row in rows:
        row["kickoff_time_utc"] = pd.NA

    validated = validate_fixture_snapshot(_frame(rows))

    assert validated["kickoff_time_utc"].isna().all()
    assert len(validated) == 2


def test_a_kickoff_time_present_on_only_one_side_is_rejected() -> None:
    """The two sides describe one match, so one cannot know the time and the other not."""

    rows = _pair()
    rows[0]["kickoff_time_utc"] = pd.NA

    with pytest.raises(InvalidValueError, match="disagrees on 'kickoff_time_utc'"):
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


# --- aggregation to team-gameweek grain -------------------------------------


def test_a_single_fixture_aggregates_to_one_home_and_one_away_club() -> None:
    aggregated = aggregate_team_gameweek(_frame(_pair(home=3, away=14)))

    home = aggregated.loc[aggregated["team_id"] == 3].iloc[0]
    away = aggregated.loc[aggregated["team_id"] == 14].iloc[0]
    assert (home["fixture_count"], home["home_fixture_count"], home["away_fixture_count"]) == (
        1,
        1,
        0,
    )
    assert (away["fixture_count"], away["home_fixture_count"], away["away_fixture_count"]) == (
        1,
        0,
        1,
    )


def test_a_double_gameweek_counts_two_fixtures_for_one_club() -> None:
    """This is the quantity the player-gameweek panel cannot express."""

    rows = _pair(1, gameweek=9, home=3, away=14) + _pair(2, gameweek=9, home=8, away=3)

    aggregated = aggregate_team_gameweek(_frame(rows))

    arsenal = aggregated.loc[(aggregated["team_id"] == 3) & (aggregated["gameweek"] == 9)].iloc[0]
    assert arsenal["fixture_count"] == 2
    assert arsenal["home_fixture_count"] == 1
    assert arsenal["away_fixture_count"] == 1


def test_difficulty_is_averaged_and_minimised_across_a_double_gameweek() -> None:
    rows = _pair(1, gameweek=9, home=3, away=14) + _pair(2, gameweek=9, home=3, away=8)
    rows[0]["fixture_difficulty"] = 2
    rows[2]["fixture_difficulty"] = 5

    aggregated = aggregate_team_gameweek(_frame(rows))

    arsenal = aggregated.loc[aggregated["team_id"] == 3].iloc[0]
    assert arsenal["mean_fixture_difficulty"] == pytest.approx(3.5)
    assert arsenal["minimum_fixture_difficulty"] == 2


def test_aggregation_reads_only_the_gameweek_it_summarises() -> None:
    """A same-gameweek aggregation must not become a window over other gameweeks."""

    rows = _pair(1, gameweek=1, home=3, away=14) + _pair(2, gameweek=2, home=3, away=8)
    baseline = aggregate_team_gameweek(_frame(rows))

    altered = _pair(1, gameweek=1, home=3, away=14) + _pair(2, gameweek=2, home=3, away=8)
    altered[2]["fixture_difficulty"] = 5
    altered[3]["fixture_difficulty"] = 1
    changed = aggregate_team_gameweek(_frame(altered))

    first = baseline.loc[baseline["gameweek"] == 1].reset_index(drop=True)
    still_first = changed.loc[changed["gameweek"] == 1].reset_index(drop=True)
    assert first.equals(still_first)


def test_two_snapshots_are_summarised_separately() -> None:
    """Summing across captures would silently double every count."""

    rows = _pair() + _pair(snapshot_id="fpl-live-20260101T000000Z-abcabcabcabc")

    aggregated = aggregate_team_gameweek(_frame(rows))

    assert aggregated["fixture_count"].tolist() == [1, 1, 1, 1]
    assert aggregated["snapshot_id"].nunique() == 2


def test_a_missing_difficulty_leaves_the_summary_empty_rather_than_zero() -> None:
    rows = _pair()
    for row in rows:
        row["fixture_difficulty"] = pd.NA

    aggregated = aggregate_team_gameweek(_frame(rows))

    assert aggregated["mean_fixture_difficulty"].isna().all()
    assert aggregated["minimum_fixture_difficulty"].isna().all()
    assert aggregated["fixture_count"].tolist() == [1, 1]


def test_counts_are_non_nullable_integers() -> None:
    aggregated = aggregate_team_gameweek(_frame(_pair()))

    for column in ("fixture_count", "home_fixture_count", "away_fixture_count"):
        assert aggregated[column].dtype == "int64"


def test_a_blank_gameweek_defaults_to_zero_fixtures_and_no_difficulty() -> None:
    """Zero difficulty would describe the easiest possible tie, not the absence of one."""

    defaults = blank_gameweek_defaults()

    assert defaults["fixture_count"] == 0
    assert defaults["home_fixture_count"] == 0
    assert defaults["away_fixture_count"] == 0
    assert pd.isna(defaults["mean_fixture_difficulty"])
    assert pd.isna(defaults["minimum_fixture_difficulty"])


def test_the_blank_gameweek_defaults_are_read_only() -> None:
    defaults = blank_gameweek_defaults()

    with pytest.raises(TypeError):
        defaults["fixture_count"] = 1  # type: ignore[index]

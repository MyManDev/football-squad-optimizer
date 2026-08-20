"""Tests for attaching a gameweek's fixture context to the player panel.

The join crosses an identifier boundary — display names in the panel, persistent codes
in the fixture table — so the bridge is exercised deliberately rather than assumed.
"""

from typing import Any

import pandas as pd
import pytest

from squadopt.data.schema import FIXTURE_COLUMNS
from squadopt.features.config import FeatureConfigurationError
from squadopt.features.fixtures import FIXTURE_FEATURE_COLUMNS, attach_fixture_features

SNAPSHOT = "vaastav-8c97b2a"
SEASON = "2025-26"

# Display name to persistent code, deliberately unequal so a test cannot pass by
# confusing the two spaces.
TEAM_CODES = pd.DataFrame(
    [
        {"season": SEASON, "name": "Arsenal", "code": 3},
        {"season": SEASON, "name": "Liverpool", "code": 14},
        {"season": SEASON, "name": "Man City", "code": 43},
    ]
)


def _player(team: str = "Arsenal", gameweek: int = 1, player_id: int = 1) -> dict[str, Any]:
    return {
        "season": SEASON,
        "gameweek": gameweek,
        "player_id": player_id,
        "name": "A",
        "team_id": team,
        "position": "MID",
        "price_tenths": 80,
        "minutes": 90,
        "total_points": 5,
    }


def _fixture_pair(
    fixture_id: int = 1,
    *,
    gameweek: int = 1,
    home: int = 3,
    away: int = 14,
    home_difficulty: int = 2,
    away_difficulty: int = 5,
    snapshot_id: str = SNAPSHOT,
    captured_at_utc: Any = pd.NA,
) -> list[dict[str, Any]]:
    shared: dict[str, Any] = {
        "snapshot_id": snapshot_id,
        "captured_at_utc": captured_at_utc,
        "season": SEASON,
        "gameweek": gameweek,
        "fixture_id": fixture_id,
        "kickoff_time_utc": "2025-08-15T19:00:00Z",
        "deadline_timestamp_utc": pd.NA,
        "status": "final",
    }
    return [
        {
            **shared,
            "team_id": home,
            "opponent_team_id": away,
            "is_home": True,
            "fixture_difficulty": home_difficulty,
        },
        {
            **shared,
            "team_id": away,
            "opponent_team_id": home,
            "is_home": False,
            "fixture_difficulty": away_difficulty,
        },
    ]


def _fixtures(rows: list[dict[str, Any]]) -> pd.DataFrame:
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


def _attach(*args: Any, **kwargs: Any) -> pd.DataFrame:
    """Attach from archive-shaped fixtures, which cannot prove a capture instant.

    Every test below this line is about the join and the counts, so each one states the
    same thing the production caller states: take the calendar, leave the difficulty.
    """

    kwargs.setdefault("unproven_difficulty", "omit")
    return attach_fixture_features(*args, **kwargs)


def _live_fixtures(**kwargs: Any) -> pd.DataFrame:
    """A capture-proven fixture frame: every row names the instant it was read."""

    return _fixtures(_fixture_pair(captured_at_utc="2025-08-14T18:00:00Z", **kwargs))


# --- the bridge -------------------------------------------------------------


def test_a_display_name_resolves_to_its_persistent_code() -> None:
    panel = pd.DataFrame([_player("Arsenal")])

    joined = _attach(panel, _fixtures(_fixture_pair()), TEAM_CODES)

    assert joined["fixture_count"].tolist() == [1]
    assert joined["home_fixture_count"].tolist() == [1]
    assert joined["away_fixture_count"].tolist() == [0]


def test_the_away_side_is_attributed_correctly() -> None:
    panel = pd.DataFrame([_player("Liverpool")])

    joined = attach_fixture_features(panel, _live_fixtures(), TEAM_CODES)

    assert joined["home_fixture_count"].tolist() == [0]
    assert joined["away_fixture_count"].tolist() == [1]
    assert joined["mean_fixture_difficulty"].tolist() == [5.0]


def test_a_club_the_bridge_does_not_name_is_rejected() -> None:
    """Silently dropping it would understate that club's fixture count."""

    panel = pd.DataFrame([_player("Everton")])

    with pytest.raises(FeatureConfigurationError, match="does not name"):
        _attach(panel, _fixtures(_fixture_pair()), TEAM_CODES)


def test_a_bridge_naming_one_club_twice_is_rejected() -> None:
    codes = pd.concat(
        [TEAM_CODES, pd.DataFrame([{"season": SEASON, "name": "Arsenal", "code": 99}])],
        ignore_index=True,
    )

    with pytest.raises(FeatureConfigurationError, match="same season and name twice"):
        _attach(pd.DataFrame([_player()]), _fixtures(_fixture_pair()), codes)


# --- the calendar -----------------------------------------------------------


def test_a_double_gameweek_is_visible_on_the_player_row() -> None:
    """The information is in the calendar, not in the player's past."""

    panel = pd.DataFrame([_player("Arsenal", gameweek=9)])
    proven = {"captured_at_utc": "2025-08-14T18:00:00Z"}
    fixtures = _fixtures(
        _fixture_pair(1, gameweek=9, home=3, away=14, **proven)
        + _fixture_pair(
            2, gameweek=9, home=43, away=3, home_difficulty=4, away_difficulty=3, **proven
        )
    )

    joined = attach_fixture_features(panel, fixtures, TEAM_CODES)

    assert joined["fixture_count"].tolist() == [2]
    assert joined["home_fixture_count"].tolist() == [1]
    assert joined["away_fixture_count"].tolist() == [1]
    assert joined["mean_fixture_difficulty"].tolist() == [pytest.approx(2.5)]
    assert joined["minimum_fixture_difficulty"].tolist() == [2]


def test_a_blank_gameweek_is_zero_fixtures_and_no_difficulty() -> None:
    """Zero difficulty would describe facing the easiest tie, not facing nobody."""

    panel = pd.DataFrame([_player("Man City")])

    joined = attach_fixture_features(panel, _live_fixtures(), TEAM_CODES)

    assert joined["fixture_count"].tolist() == [0]
    assert joined["home_fixture_count"].tolist() == [0]
    assert joined["away_fixture_count"].tolist() == [0]
    assert joined["mean_fixture_difficulty"].isna().all()
    assert joined["minimum_fixture_difficulty"].isna().all()


def test_counts_are_non_nullable_integers_even_after_a_blank() -> None:
    panel = pd.DataFrame([_player("Arsenal"), _player("Man City", player_id=2)])

    joined = _attach(panel, _fixtures(_fixture_pair()), TEAM_CODES)

    for column in ("fixture_count", "home_fixture_count", "away_fixture_count"):
        assert joined[column].dtype == "int64"


def test_a_gameweek_reads_only_its_own_fixtures() -> None:
    """Fixture context is pre-match, so it is read from the target row, not windowed."""

    panel = pd.DataFrame([_player("Arsenal", gameweek=1), _player("Arsenal", gameweek=2)])
    fixtures = _fixtures(
        _fixture_pair(1, gameweek=1) + _fixture_pair(2, gameweek=2) + _fixture_pair(3, gameweek=2)
    )

    joined = _attach(panel, fixtures, TEAM_CODES).set_index("gameweek")

    assert joined.loc[1, "fixture_count"] == 1
    assert joined.loc[2, "fixture_count"] == 2


# --- snapshots --------------------------------------------------------------


def test_two_snapshots_of_one_season_are_refused() -> None:
    """Joining both would duplicate every row; picking one would hide the choice."""

    fixtures = _fixtures(
        _fixture_pair(1) + _fixture_pair(1, snapshot_id="fpl-live-20260101T000000Z-abcabcabcabc")
    )

    with pytest.raises(FeatureConfigurationError, match="more than one snapshot"):
        _attach(pd.DataFrame([_player()]), fixtures, TEAM_CODES)


# --- shape ------------------------------------------------------------------


def test_row_count_is_preserved() -> None:
    panel = pd.DataFrame([_player(player_id=index) for index in range(1, 6)])

    joined = _attach(panel, _fixtures(_fixture_pair()), TEAM_CODES)

    assert len(joined) == 5


def test_the_input_frames_are_not_modified() -> None:
    panel = pd.DataFrame([_player()])
    fixtures = _fixtures(_fixture_pair())
    before_panel = panel.copy(deep=True)
    before_fixtures = fixtures.copy(deep=True)

    _attach(panel, fixtures, TEAM_CODES)

    assert panel.equals(before_panel)
    assert fixtures.equals(before_fixtures)


def test_existing_fixture_columns_are_not_silently_overwritten() -> None:
    panel = pd.DataFrame([_player()]).assign(fixture_count=99)

    with pytest.raises(FeatureConfigurationError, match="collide"):
        _attach(panel, _fixtures(_fixture_pair()), TEAM_CODES)


def test_every_declared_feature_column_is_attached_from_a_proven_capture() -> None:
    joined = attach_fixture_features(pd.DataFrame([_player()]), _live_fixtures(), TEAM_CODES)

    for column in FIXTURE_FEATURE_COLUMNS:
        assert column in joined.columns


@pytest.mark.parametrize("missing", ["season", "gameweek", "team_id"])
def test_a_panel_missing_a_join_key_is_rejected(missing: str) -> None:
    panel = pd.DataFrame([_player()]).drop(columns=[missing])

    with pytest.raises(FeatureConfigurationError, match=missing):
        _attach(panel, _fixtures(_fixture_pair()), TEAM_CODES)


def test_an_empty_panel_is_rejected() -> None:
    with pytest.raises(FeatureConfigurationError, match="no rows"):
        _attach(
            pd.DataFrame(columns=["season", "gameweek", "team_id"]),
            _fixtures(_fixture_pair()),
            TEAM_CODES,
        )


# --- the difficulty columns need a source that can prove its instant ---------


def test_archive_fixtures_refuse_to_supply_a_difficulty_by_default() -> None:
    """The default is a refusal, not a quiet omission.

    A silent absence is how a study loses a column, reports a different number, and
    nobody notices. The message names the snapshot at fault so the reader does not have to
    work out which source is unproven.
    """

    panel = pd.DataFrame([_player("Arsenal")])

    with pytest.raises(FeatureConfigurationError) as raised:
        attach_fixture_features(panel, _fixtures(_fixture_pair()), TEAM_CODES)

    message = str(raised.value)
    assert SNAPSHOT in message
    assert "not a pre-match value" in message
    assert "unproven_difficulty='omit'" in message


def test_omitting_leaves_the_calendar_and_drops_the_difficulty() -> None:
    """Absent rather than empty: a reader fails on a missing column, not on nulls."""

    panel = pd.DataFrame([_player("Arsenal")])

    joined = attach_fixture_features(
        panel, _fixtures(_fixture_pair()), TEAM_CODES, unproven_difficulty="omit"
    )

    assert joined["fixture_count"].tolist() == [1]
    assert joined["home_fixture_count"].tolist() == [1]
    assert "mean_fixture_difficulty" not in joined.columns
    assert "minimum_fixture_difficulty" not in joined.columns


def test_a_proven_capture_still_supplies_the_difficulty() -> None:
    """The rule is about provenance, not about the column being unwelcome.

    A live capture names the instant it was read, so its difficulty is genuinely a
    pre-match value and is attached without an opt-in.
    """

    panel = pd.DataFrame([_player("Arsenal")])

    joined = attach_fixture_features(panel, _live_fixtures(), TEAM_CODES)

    assert joined["mean_fixture_difficulty"].tolist() == [2.0]
    assert joined["minimum_fixture_difficulty"].tolist() == [2]


def test_there_is_no_option_that_attaches_an_unproven_difficulty() -> None:
    """The escape hatch omits; it never launders the archived value into a feature."""

    panel = pd.DataFrame([_player("Arsenal")])

    with pytest.raises(FeatureConfigurationError, match="must be 'refuse' or 'omit'"):
        attach_fixture_features(
            panel,
            _fixtures(_fixture_pair()),
            TEAM_CODES,
            unproven_difficulty="attach",  # type: ignore[arg-type]
        )


def test_a_fixture_frame_without_the_capture_column_is_treated_as_unproven() -> None:
    """A frame that cannot even be asked the question has not answered it."""

    panel = pd.DataFrame([_player("Arsenal")])
    fixtures = _live_fixtures().drop(columns=["captured_at_utc"])

    with pytest.raises(FeatureConfigurationError, match="no capture instant"):
        attach_fixture_features(panel, fixtures, TEAM_CODES)

"""The forced-chip window runner's pure parts: the calendar, the named week, the comparison."""

import pandas as pd
import pytest
from scripts.measure_forced_chip_window import (
    NAMEABLE_CHIPS,
    calendar_from,
    compare,
    named_weeks,
)


def _fixtures(rows: list[tuple[int, int]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["gameweek", "team_id"])


def test_a_club_with_no_fixture_row_is_a_stated_blank() -> None:
    """Counting only the rows present would make a blank week look like an ordinary one."""

    calendar = calendar_from(
        # Club 3 has no row in gameweek 6; club 1 plays twice in gameweek 7.
        _fixtures([(6, 1), (6, 2), (7, 1), (7, 1), (7, 2), (7, 3)]),
        gameweeks=[6, 7],
        clubs=[1, 2, 3],
    )
    six, seven = calendar
    assert six.gameweek == 6 and seven.gameweek == 7
    assert dict(six.fixture_count_by_club) == {1: 1, 2: 1, 3: 0}
    assert six.clubs_blank == 1 and six.clubs_doubling == 0
    assert dict(seven.fixture_count_by_club) == {1: 2, 2: 1, 3: 1}
    assert seven.clubs_doubling == 1 and seven.clubs_blank == 0
    # A gameweek with no rows at all is every club blank, not an absent gameweek.
    (empty,) = calendar_from(_fixtures([(6, 1)]), gameweeks=[9], clubs=[1, 2])
    assert dict(empty.fixture_count_by_club) == {1: 0, 2: 0} and empty.clubs_blank == 2


def _forecast(chips: list[dict[str, object]]) -> dict[str, object]:
    return {"chips": chips}


def test_only_a_hold_that_names_a_week_inside_the_window_is_read() -> None:
    forecast = _forecast(
        [
            # Read: a hold pointing at a week inside the window.
            {
                "name": "bboost",
                "verdict": "hold",
                "points_at_gameweek": {"gameweek": 8, "estimated_gain": 20.0},
            },
            # Not read: the rule says play it now, so there is nothing to prepare for.
            {
                "name": "3xc",
                "verdict": "play_now",
                "points_at_gameweek": None,
            },
        ]
    )
    assert named_weeks(forecast, first=6, last=9) == {"bboost": 8}

    # Not read: a hold that names no later week at all.
    assert (
        named_weeks(
            _forecast([{"name": "bboost", "verdict": "hold", "points_at_gameweek": None}]),
            first=6,
            last=9,
        )
        == {}
    )
    # Not read: a week outside the window being solved, on either side.
    outside = _forecast(
        [{"name": "bboost", "verdict": "hold", "points_at_gameweek": {"gameweek": 12}}]
    )
    assert named_weeks(outside, first=6, last=9) == {}
    assert named_weeks(outside, first=6, last=12) == {"bboost": 12}
    # And the decision gameweek itself is never "a later week".
    now = _forecast([{"name": "bboost", "verdict": "hold", "points_at_gameweek": {"gameweek": 5}}])
    assert named_weeks(now, first=6, last=9) == {}

    assert set(NAMEABLE_CHIPS) == {"3xc", "bboost"}


def _arm(status: str, value: float, gap: float, **week: object) -> dict[str, object]:
    first = {
        "gameweek": 6,
        "transfers_in": [1],
        "transfers_out": [2],
        "captain_id": 3,
        "starting_xi": [1, 3],
        "paid_transfers": 0,
    }
    first.update(week)
    return {
        "arm": "x",
        "solver_status": status,
        "plan_value": value,
        "absolute_gap": gap,
        "first_week": first,
    }


def test_a_value_difference_counts_only_when_both_arms_are_proved() -> None:
    both = compare(_arm("OPTIMAL", 100.0, 0.0), _arm("OPTIMAL", 104.0, 0.0))
    assert both["value_difference_attributable"] is True
    assert both["plan_value_difference"] == pytest.approx(4.0)
    assert both["largest_open_gap"] is None
    assert both["first_week_differs"] is False and both["first_week_differences"] == {}

    # One arm unproved: the difference is printed with the gap and counts for nothing.
    one = compare(_arm("OPTIMAL", 100.0, 0.0), _arm("FEASIBLE", 104.0, 9.5))
    assert one["value_difference_attributable"] is False
    assert one["both_arms_proved"] is False
    assert one["largest_open_gap"] == pytest.approx(9.5)
    assert one["plan_value_difference"] == pytest.approx(4.0)


def test_the_first_week_difference_names_what_changed() -> None:
    changed = compare(
        _arm("OPTIMAL", 100.0, 0.0),
        _arm("OPTIMAL", 104.0, 0.0, transfers_in=[7], captain_id=9, paid_transfers=1),
    )
    assert changed["first_week_differs"] is True
    assert set(changed["first_week_differences"]) == {
        "transfers_in",
        "captain_id",
        "paid_transfers",
    }
    assert changed["first_week_differences"]["captain_id"] == (3, 9)
    # The gameweek itself is not a difference to report: both arms plan the same week.
    assert "gameweek" not in changed["first_week_differences"]

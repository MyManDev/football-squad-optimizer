"""One artifact forecasts the weeks it is asked for, from the capture's target and no earlier.

The producer forecast exactly five weeks from the target, and that is still what it does
when nobody asks otherwise. A research caller may ask for a longer run, and the run must
start where the served artifact starts, because the first week is the decided forecast.
The extension is week-range-invariant: a fixture's forecast does not depend on which other
weeks are forecast beside it, so a longer run leaves the served weeks' numbers alone.
"""

import numpy as np
import pandas as pd
import pytest
from tests.unit.test_football_development import football_fixture  # noqa: F401

from squadopt.application.football_live import forecast_gameweeks
from squadopt.live.football_horizon import build_football_horizon


@pytest.mark.parametrize(
    ("first", "expected"),
    [(6, (6, 7, 8, 9, 10)), (34, (34, 35, 36, 37, 38)), (36, (36, 37, 38)), (38, (38,))],
)
def test_unasked_the_producer_forecasts_the_served_five_weeks_and_fewer_at_the_season_end(
    first, expected
):
    assert forecast_gameweeks(first) == expected
    assert forecast_gameweeks(first, None) == expected


def test_a_named_run_is_kept_as_plain_integers_from_the_target():
    assert forecast_gameweeks(6, range(6, 20)) == tuple(range(6, 20))
    named = forecast_gameweeks(6, [np.int64(6), np.int64(7)])
    assert named == (6, 7)
    assert all(type(week) is int for week in named)


@pytest.mark.parametrize(
    ("gameweeks", "match"),
    [
        ((), "nonempty"),
        ((6, True), "integers"),
        ((6.0, 7.0), "integers"),
        ((7, 8, 9), "start at the capture"),
        ((6, 8), "consecutive"),
        ((6, 7, 7), "consecutive"),
        (range(6, 40), "end by gameweek 38"),
    ],
)
def test_a_run_that_does_not_start_at_the_target_or_skips_a_week_is_refused(gameweeks, match):
    with pytest.raises(ValueError, match=match):
        forecast_gameweeks(6, gameweeks)


def test_a_longer_run_leaves_the_served_weeks_numbers_alone(football_fixture):  # noqa: F811
    model, history, roster, fixtures, _ = football_fixture
    kwargs = dict(
        season="2025-26",
        source_snapshot_id="synthetic",
        captured_at=model.cutoff - pd.Timedelta(hours=1),
    )
    served, served_parts = build_football_horizon(
        model, history, roster, fixtures, gameweeks=(17,), **kwargs
    )
    extended, extended_parts = build_football_horizon(
        model, history, roster, fixtures, gameweeks=(17, 18), **kwargs
    )
    assert set(extended.table.gameweek) == {17, 18}
    assert extended.table.loc[extended.table.gameweek.eq(18), "expected_points"].sum() > 0
    order = ["gameweek", "player_id"]
    pd.testing.assert_frame_equal(
        served.table.sort_values(order).reset_index(drop=True),
        extended.table.loc[extended.table.gameweek.eq(17)]
        .sort_values(order)
        .reset_index(drop=True),
        check_exact=False,
        atol=1e-10,
        rtol=0,
    )
    keys = ["fixture", "player_code"]
    pd.testing.assert_frame_equal(
        served_parts.sort_values(keys).reset_index(drop=True),
        extended_parts.loc[extended_parts.GW.eq(17)].sort_values(keys).reset_index(drop=True),
        check_exact=False,
        atol=1e-10,
        rtol=0,
    )

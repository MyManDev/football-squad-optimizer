"""One artifact forecasts the weeks it is asked for, from the capture's target and no earlier.

The producer forecast exactly five weeks from the target, and that is still what it does
when nobody asks otherwise. A research caller may ask for a longer run, and the run must
start where the served artifact starts, because the first week is the decided forecast.
The extension is week-range-invariant: a fixture's forecast does not depend on which other
weeks are forecast beside it, so a longer run leaves the served weeks' numbers alone.
"""

import json

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


def _producer_world(monkeypatch, first: int = 6):
    """The producer with its archive, model and forecaster stubbed at the module boundary.

    What is left real is the producer's own wiring: which weeks it takes from the
    capture's calendar and hands to the forecaster, and which weeks its document carries.
    """
    from types import SimpleNamespace

    from squadopt.application import football_live

    calls: list[tuple[int, ...]] = []
    history = pd.DataFrame(
        {
            "season": ["2025-26", "2025-26"],
            "kickoff": pd.to_datetime(["2026-05-01T14:00:00Z", "2026-05-08T14:00:00Z"]),
        }
    )

    class Model:
        def __init__(self, training, history, *, cutoff):
            self.cutoff = cutoff

    def build(
        model, history, roster, calendar, *, gameweeks, season, source_snapshot_id, captured_at
    ):
        calls.append(tuple(gameweeks))
        assert set(calendar.GW) == set(gameweeks)
        rows = [
            dict(
                gameweek=week,
                player_id=int(player),
                name=str(player),
                team_id=1,
                position="MID",
                price_tenths=50,
                expected_points=1.0,
                fixture_count=1,
                home_fixture_count=0,
            )
            for week in gameweeks
            for player in roster.player_id
        ]
        return SimpleNamespace(table=pd.DataFrame(rows)), pd.DataFrame()

    inputs = SimpleNamespace(
        captured_at_utc="2026-09-22T20:55:33Z",
        deadline=SimpleNamespace(gameweek=first),
        players=pd.DataFrame({"player_id": [101, 102]}),
        snapshot_id="synthetic",
        availability=None,
    )
    fixtures = [
        dict(
            id=week * 10,
            team_h=1,
            team_a=2,
            event=week,
            kickoff_time=f"2026-10-{week + 4:02d}T14:00:00Z",
        )
        for week in range(first, first + 8)
    ]
    snapshot = SimpleNamespace(
        payloads={
            "bootstrap-static.json": json.dumps(
                {
                    "teams": [{"id": 1, "code": 10}, {"id": 2, "code": 20}],
                    "elements": [{"code": 101, "team": 1}, {"code": 102, "team": 2}],
                }
            ),
            "fixtures.json": json.dumps(fixtures),
        },
        metadata=SimpleNamespace(fingerprint="fingerprint"),
    )
    monkeypatch.setattr(football_live, "infer_season", lambda snapshot: "2026-27")
    monkeypatch.setattr(football_live, "read_inputs", lambda snapshot, *, season: inputs)
    monkeypatch.setattr(football_live, "archive_history", lambda root: history)
    monkeypatch.setattr(football_live, "captured_history", lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr(football_live, "causal_training", lambda history: pd.DataFrame({"x": [1]}))
    monkeypatch.setattr(football_live, "FixtureFootballModel", Model)
    monkeypatch.setattr(football_live, "build_football_horizon", build)
    monkeypatch.setattr(football_live, "ARCHIVE_SEASONS", ())
    return football_live, snapshot, calls


def test_the_producer_hands_the_named_weeks_to_the_forecaster_and_carries_them(
    monkeypatch, tmp_path
):
    football_live, snapshot, calls = _producer_world(monkeypatch)
    served = football_live.produce_football_forecast(snapshot, tmp_path)
    assert calls == [(6, 7, 8, 9, 10)]
    assert {row["gameweek"] for row in served["rows"]} == set(range(6, 11))
    extended = football_live.produce_football_forecast(snapshot, tmp_path, gameweeks=range(6, 13))
    assert calls[-1] == tuple(range(6, 13))
    assert {row["gameweek"] for row in extended["rows"]} == set(range(6, 13))
    assert extended["gameweek"] == served["gameweek"] == 6
    assert extended["fingerprint"] != served["fingerprint"]
    with pytest.raises(ValueError, match="start at the capture"):
        football_live.produce_football_forecast(snapshot, tmp_path, gameweeks=range(7, 12))

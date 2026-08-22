"""Tests for the in-season blend: the opening control told about the season so far.

Two properties carry the design and both are easy to lose. The first is that the two
stages are blended separately, so playing time and scoring rate stay distinguishable —
blending the finished points instead collapses algebraically to season-to-date points per
gameweek and throws the minutes away. The second is that a lone in-season observation is
never taken at face value: the first version of this module did exactly that, and a single
seventy-five-minute appearance out-projected the best player in the game.
"""

import pandas as pd
import pytest

from squadopt.features import PRIOR_MINUTES_COLUMN, PRIOR_RATE_COLUMN
from squadopt.prediction.config import PredictionConfigurationError
from squadopt.prediction.in_season import (
    InSeasonBlendConfig,
    blend_in_season_projection,
    in_season_rate_weight,
    in_season_weight,
)

ROSTER_COLUMNS = ("player_id", "name", "team_id", "position", "price_tenths")


def _roster(*codes: int, position: str = "MID", price: int = 65) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "player_id": code,
                "name": f"Player {code}",
                "team_id": "Arsenal",
                "position": position,
                "price_tenths": price,
            }
            for code in codes
        ],
        columns=list(ROSTER_COLUMNS),
    )


def _carried(rows: dict[int, tuple[float, float]]) -> pd.DataFrame:
    """Map code -> (minutes per gameweek, points per 90). Absent codes carry nothing."""

    return pd.DataFrame(
        [
            {
                "player_id": code,
                PRIOR_MINUTES_COLUMN: minutes,
                PRIOR_RATE_COLUMN: rate,
            }
            for code, (minutes, rate) in rows.items()
        ],
        columns=["player_id", PRIOR_MINUTES_COLUMN, PRIOR_RATE_COLUMN],
    ).astype({PRIOR_MINUTES_COLUMN: "float64", PRIOR_RATE_COLUMN: "float64"})


def _history(rows: dict[int, tuple[int, int]]) -> pd.DataFrame:
    """Map code -> (minutes, total_points) so far this season."""

    return pd.DataFrame(
        [
            {"player_id": code, "minutes": minutes, "total_points": points}
            for code, (minutes, points) in rows.items()
        ],
        columns=["player_id", "minutes", "total_points"],
    )


def _fallback(rows: dict[int, float]) -> pd.DataFrame:
    return pd.DataFrame(
        [{"player_id": code, "expected_points": value} for code, value in rows.items()],
        columns=["player_id", "expected_points"],
    )


def _points(blend: object, code: int) -> float:
    table = blend.table  # type: ignore[attr-defined]
    return float(table.loc[table["player_id"] == code, "expected_points"].iloc[0])


# --- the declared weights ----------------------------------------------------


@pytest.mark.parametrize(
    ("played", "expected"),
    [(0, 0.0), (1, 1 / 7), (2, 0.25), (6, 0.5), (12, 2 / 3), (18, 0.75)],
)
def test_the_gameweek_weight_follows_the_declared_schedule(played: int, expected: float) -> None:
    """played / (played + 6): an even split exactly when the control's window fills."""

    assert in_season_weight(played) == pytest.approx(expected)


def test_the_gameweek_weight_is_zero_before_anything_is_played() -> None:
    assert in_season_weight(0) == 0.0


@pytest.mark.parametrize(
    ("minutes", "expected"), [(0, 0.0), (8, 8 / 278), (90, 0.25), (270, 0.5), (1080, 0.8)]
)
def test_the_rate_weight_is_shrunk_by_minutes_not_gameweeks(minutes: int, expected: float) -> None:
    """A rate's sample is minutes. Eight of them is a gameweek and almost no evidence."""

    weights = in_season_rate_weight(pd.Series([float(minutes)]))

    assert float(weights.iloc[0]) == pytest.approx(expected)


def test_a_cameo_earns_far_less_rate_weight_than_a_full_match() -> None:
    weights = in_season_rate_weight(pd.Series([8.0, 90.0]))

    assert float(weights.iloc[0]) < float(weights.iloc[1]) / 5


# --- the correction that matters ---------------------------------------------


def test_one_appearance_without_a_carried_record_is_not_taken_at_face_value() -> None:
    """The regression this module was rewritten for.

    A player who played 75 minutes for 6 points and has no completed season extrapolates
    to 6.0 expected points, which put him above the best player in the game. The answer
    has to sit between that extrapolation and the price prior the opening control gives
    exactly these players.
    """

    blend = blend_in_season_projection(
        _roster(1),
        _carried({}),
        _history({1: (75, 6)}),
        _fallback({1: 1.9461}),
        gameweeks_played=1,
    )

    projected = _points(blend, 1)
    assert 1.9461 < projected < 6.0
    assert projected == pytest.approx(0.217391 * 6.0 + 0.782609 * 1.9461, abs=1e-4)
    assert blend.players_shrunk_against_the_price_prior == 1
    assert blend.players_blended_two_stage == 0


def test_the_shrunk_answer_moves_with_how_much_was_played() -> None:
    """Ninety minutes should say more than nine, at the same points per ninety."""

    def projected(minutes: int, points: int) -> float:
        blend = blend_in_season_projection(
            _roster(1),
            _carried({}),
            _history({1: (minutes, points)}),
            _fallback({1: 2.0}),
            gameweeks_played=1,
        )
        return _points(blend, 1)

    # Both are 6 points per 90; only the sample differs.
    assert projected(9, 1) < projected(90, 6)


def test_a_player_who_has_not_played_is_untouched_by_the_in_season_term() -> None:
    """No minutes is no rate. The carried record answers alone."""

    with_history = blend_in_season_projection(
        _roster(1),
        _carried({1: (80.0, 5.0)}),
        _history({1: (0, 0)}),
        _fallback({1: 2.0}),
        gameweeks_played=1,
    )

    # minutes blend still moves, because zero minutes is an observation about playing time
    assert _points(with_history, 1) < 80.0 * 5.0 / 90.0
    assert with_history.players_with_in_season_minutes == 0


# --- the two stages stay separate -------------------------------------------


def test_playing_time_and_scoring_rate_are_blended_separately() -> None:
    """The property a points-scale blend cannot have.

    Two players with a carried record, the same carried numbers, the same in-season
    points, and different in-season minutes must not receive the same projection. If the
    module blended finished points they would, because points per gameweek is identical.
    """

    carried = _carried({1: (80.0, 5.0), 2: (80.0, 5.0)})
    blend = blend_in_season_projection(
        _roster(1, 2),
        carried,
        _history({1: (90, 4), 2: (20, 4)}),
        _fallback({1: 2.0, 2: 2.0}),
        gameweeks_played=1,
    )

    assert _points(blend, 1) != pytest.approx(_points(blend, 2))
    assert blend.players_blended_two_stage == 2


def test_a_small_minutes_high_return_cameo_can_still_out_project_a_full_match() -> None:
    """Pins a consequence of the design that is worth knowing rather than discovering.

    Twenty minutes for four points is a per-ninety rate of eighteen, and although it earns
    only 7% rate weight against 25% for the ninety-minute player, the raw value is large
    enough that the shrunk estimate still lands higher. Each stage is shrunk in its own
    unit and each weight is individually defensible -- a single gameweek of playing time is
    a full gameweek of evidence about playing time, while twenty minutes is only twenty
    minutes of evidence about a rate -- but the combination means a cameo is not fully
    discounted.

    Whether the 270-minute rate prior is strong enough is a question for a walk-forward
    measurement over completed seasons, not for an intuition asserted in a test. This test
    exists so that measurement has a recorded starting point to move.
    """

    blend = blend_in_season_projection(
        _roster(1, 2),
        _carried({1: (80.0, 5.0), 2: (80.0, 5.0)}),
        _history({1: (90, 4), 2: (20, 4)}),
        _fallback({1: 2.0, 2: 2.0}),
        gameweeks_played=1,
    )

    full_match = _points(blend, 1)
    cameo = _points(blend, 2)

    assert full_match == pytest.approx(4.2976, abs=1e-4)
    assert cameo == pytest.approx(4.6798, abs=1e-4)
    # The cameo's advantage comes from the rate stage; its playing-time estimate is lower,
    # which is the part that keeps the gap small rather than large.
    assert cameo > full_match
    assert cameo / full_match < 1.15


# --- coverage is enforced here, because nothing downstream can ---------------


def test_every_rostered_player_carries_a_number() -> None:
    """A code missing from a handoff is read downstream as zero and never selected."""

    blend = blend_in_season_projection(
        _roster(1, 2, 3),
        _carried({1: (80.0, 5.0)}),
        _history({2: (45, 3)}),
        _fallback({1: 2.0, 2: 2.0, 3: 2.0}),
        gameweeks_played=1,
    )

    assert len(blend.table) == 3
    assert bool(blend.table["expected_points"].notna().all())
    assert set(blend.table["player_id"]) == {1, 2, 3}


def test_the_route_counts_account_for_every_player() -> None:
    blend = blend_in_season_projection(
        _roster(1, 2, 3, 4),
        _carried({1: (80.0, 5.0), 3: (40.0, 3.0)}),
        _history({1: (90, 5), 2: (60, 2)}),
        _fallback({code: 2.0 for code in (1, 2, 3, 4)}),
        gameweeks_played=1,
    )

    accounted = (
        blend.players_blended_two_stage
        + blend.players_shrunk_against_the_price_prior
        + blend.players_from_carry_over_only
        + blend.players_priced_from_the_prior
    )
    assert accounted == blend.players == 4


def test_a_player_with_no_record_and_no_fallback_price_is_refused() -> None:
    """Silently emitting nothing for him would make him unselectable without saying so."""

    with pytest.raises(PredictionConfigurationError, match="every rostered player"):
        blend_in_season_projection(
            _roster(1, 2),
            _carried({1: (80.0, 5.0)}),
            _history({}),
            _fallback({1: 2.0}),
            gameweeks_played=1,
        )


def test_expected_points_are_never_negative() -> None:
    blend = blend_in_season_projection(
        _roster(1),
        _carried({1: (80.0, -4.0)}),
        _history({1: (90, -2)}),
        _fallback({1: 1.0}),
        gameweeks_played=1,
    )

    assert _points(blend, 1) >= 0.0


def test_output_is_sorted_by_player_id() -> None:
    blend = blend_in_season_projection(
        _roster(30, 10, 20),
        _carried({}),
        _history({}),
        _fallback({10: 1.0, 20: 2.0, 30: 3.0}),
        gameweeks_played=1,
    )

    assert blend.table["player_id"].tolist() == [10, 20, 30]


# --- refusals ----------------------------------------------------------------


@pytest.mark.parametrize("played", [0, -1])
def test_a_season_that_has_not_started_belongs_to_the_opening_control(played: int) -> None:
    with pytest.raises(PredictionConfigurationError, match="opening control"):
        blend_in_season_projection(
            _roster(1), _carried({}), _history({}), _fallback({1: 2.0}), gameweeks_played=played
        )


def test_a_duplicated_roster_code_is_refused() -> None:
    roster = pd.concat([_roster(1), _roster(1)], ignore_index=True)

    with pytest.raises(PredictionConfigurationError, match="repeats a player_id"):
        blend_in_season_projection(
            roster, _carried({}), _history({}), _fallback({1: 2.0}), gameweeks_played=1
        )


def test_an_empty_roster_is_refused() -> None:
    with pytest.raises(PredictionConfigurationError, match="at least one player"):
        blend_in_season_projection(
            _roster(), _carried({}), _history({}), _fallback({}), gameweeks_played=1
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [("prior_gameweek_equivalent", 0), ("prior_minute_equivalent", 0)],
)
def test_a_weight_prior_below_one_is_refused(field: str, value: int) -> None:
    with pytest.raises(PredictionConfigurationError, match="at least 1"):
        InSeasonBlendConfig(**{field: value})


def test_the_declared_defaults_are_the_ones_the_docstring_names() -> None:
    """These two numbers are the model. A silent change to either is a new model."""

    config = InSeasonBlendConfig()

    assert config.prior_gameweek_equivalent == 6
    assert config.prior_minute_equivalent == 270


def test_the_diagnostics_report_both_weights() -> None:
    """A weekly report has to be able to say how much of the answer was the season so far."""

    blend = blend_in_season_projection(
        _roster(1),
        _carried({1: (80.0, 5.0)}),
        _history({1: (90, 5)}),
        _fallback({1: 2.0}),
        gameweeks_played=1,
    )

    diagnostics = blend.diagnostics
    assert diagnostics["in_season_weight"] == pytest.approx(1 / 7)
    assert diagnostics["carry_over_weight"] == pytest.approx(6 / 7)
    assert diagnostics["gameweeks_played"] == 1

"""Tests for the opponent-strength signal measurement.

The measurement's conclusion turns on two things that are easy to get quietly wrong: which
side of the ball each position group is scored against, and whether a spread comes with a
trend. Both get their own tests, because a spread with no trend and a spread with one are
different evidence and the report says which it found.
"""

from typing import Any

import pandas as pd
import pytest

from squadopt.backtest.opponent_strength_signal import (
    OPPONENT_STRENGTH_SIGNAL_CONTRACT_VERSION,
    SIDES,
    _monotone,
    measure_opponent_strength_signal,
    signal_to_dict,
    signal_to_markdown,
)
from squadopt.backtest.splits import BacktestConfigurationError

SEASON = "2024-25"
CLUBS = ((1, 3, "Alpha"), (2, 7, "Beta"), (3, 91, "Gamma"), (4, 94, "Delta"))
POSITIONS = ("GK", "DEF", "MID", "FWD")
GAMEWEEKS = 8


def _team_codes() -> pd.DataFrame:
    return pd.DataFrame(
        [{"season": SEASON, "id": ident, "code": code, "name": name} for ident, code, name in CLUBS]
    )


def _panel() -> pd.DataFrame:
    """Four clubs, each with one player per position, over several gameweeks."""

    rows: list[dict[str, Any]] = []
    for gameweek in range(1, GAMEWEEKS + 1):
        for index, (_, _, name) in enumerate(CLUBS):
            for position_index, position in enumerate(POSITIONS):
                player = index * 10 + position_index
                rows.append(
                    {
                        "season": SEASON,
                        "gameweek": gameweek,
                        "player_id": player,
                        "name": f"Player {player}",
                        "team_id": name,
                        "position": position,
                        "price_tenths": 50,
                        "minutes": 90,
                        # Clubs differ in strength so the quartiles are not degenerate.
                        "total_points": 2 + index + (gameweek % 3),
                    }
                )
    return pd.DataFrame(rows)


def _fixtures() -> pd.DataFrame:
    """Each gameweek pairs the clubs, rotating so opponents vary."""

    rows: list[dict[str, Any]] = []
    codes = [code for _, code, _ in CLUBS]
    for gameweek in range(1, GAMEWEEKS + 1):
        pairs = (
            [(codes[0], codes[1]), (codes[2], codes[3])]
            if gameweek % 2
            else [(codes[0], codes[2]), (codes[1], codes[3])]
        )
        for home, away in pairs:
            for team, opponent in ((home, away), (away, home)):
                rows.append(
                    {
                        "season": SEASON,
                        "gameweek": gameweek,
                        "team_id": team,
                        "opponent_team_id": opponent,
                    }
                )
    return pd.DataFrame(rows)


def _residuals(panel: pd.DataFrame) -> pd.DataFrame:
    """A residual table shaped like `oos_residual_export_v1`."""

    frame = panel.loc[panel["gameweek"] > 1].copy(deep=True)
    frame["fold_id"] = frame["gameweek"].map(lambda value: f"{SEASON}-gw{int(value):02d}")
    frame["realized_points"] = frame["total_points"].astype("float64")
    frame["predicted_points"] = 2.5
    frame["residual"] = frame["realized_points"] - frame["predicted_points"]
    return frame.loc[
        :,
        [
            "fold_id",
            "season",
            "gameweek",
            "player_id",
            "team_id",
            "position",
            "predicted_points",
            "realized_points",
            "residual",
        ],
    ]


def _measure(**kwargs: Any) -> Any:
    panel = _panel()
    return measure_opponent_strength_signal(
        kwargs.pop("residuals", _residuals(panel)),
        panel,
        _fixtures(),
        _team_codes(),
        window=kwargs.pop("window", 3),
        **kwargs,
    )


# --- the sides are kept apart -----------------------------------------------


def test_each_side_is_scored_against_the_opposing_unit() -> None:
    """An attacker's opponent is a defence; folding them together describes neither."""

    assert SIDES[0][1] == ("MID", "FWD")
    assert SIDES[0][2] == "opponent_defence_strength"
    assert SIDES[1][1] == ("GK", "DEF")
    assert SIDES[1][2] == "opponent_attack_strength"


def test_both_sides_are_reported_separately() -> None:
    result = _measure()

    assert {side.side for side in result.sides} == {"attacking", "defensive"}


def test_every_quartile_reports_the_rows_behind_it() -> None:
    for side in _measure().sides:
        assert all(row.observations > 0 for row in side.quartiles)


# --- raw against residual ---------------------------------------------------


def test_both_the_raw_and_the_residual_effect_are_reported() -> None:
    """Quoting only the raw effect would overstate what a new feature could buy."""

    document = signal_to_dict(_measure())

    for side in document["sides"]:  # type: ignore[union-attr]
        assert "raw_spread" in side
        assert "residual_spread" in side


def test_the_surviving_ratio_divides_residual_by_raw() -> None:
    for side in _measure().sides:
        if side.raw_spread != 0.0:
            assert side.surviving_ratio == pytest.approx(side.residual_spread / side.raw_spread)


def test_a_zero_raw_spread_leaves_the_ratio_undefined() -> None:
    """Reporting it as zero would claim the effect vanished rather than that it is unmeasurable."""

    import math

    from squadopt.backtest.opponent_strength_signal import SideSignal

    side = SideSignal(
        side="attacking",
        positions=("MID",),
        strength_column="opponent_defence_strength",
        observations=1,
        quartiles=(),
        raw_spread=0.0,
        residual_spread=0.5,
        raw_monotone=True,
        residual_monotone=True,
    )

    assert math.isnan(side.surviving_ratio)


# --- monotonicity -----------------------------------------------------------


def test_a_one_way_trend_is_monotone() -> None:
    assert _monotone([3.0, 2.0, 1.0, 0.0])
    assert _monotone([0.0, 1.0, 2.0, 3.0])


def test_a_trend_the_middle_contradicts_is_not_monotone() -> None:
    """Two noisy end quartiles can produce a gap the middle does not support."""

    assert not _monotone([3.0, 1.0, 2.0, 0.0])


def test_monotonicity_is_reported_for_both_measures() -> None:
    document = signal_to_dict(_measure())

    for side in document["sides"]:  # type: ignore[union-attr]
        assert isinstance(side["raw_monotone"], bool)
        assert isinstance(side["residual_monotone"], bool)


# --- the record -------------------------------------------------------------


def test_the_record_states_it_is_not_gate_evidence() -> None:
    document = signal_to_dict(_measure())

    assert document["gate_evidence"] is False
    assert document["locked_holdout_accessed"] is False
    assert document["contract_version"] == OPPONENT_STRENGTH_SIGNAL_CONTRACT_VERSION


def test_the_report_names_the_limits_a_reader_needs() -> None:
    text = signal_to_markdown(_measure())

    assert "not gate evidence" in text
    assert "own declaration" in text
    assert "proxy" in text


# --- inputs -----------------------------------------------------------------


def test_a_residual_table_missing_columns_is_refused() -> None:
    panel = _panel()
    with pytest.raises(BacktestConfigurationError, match="missing columns"):
        _measure(residuals=_residuals(panel).drop(columns=["residual"]))


def test_a_residual_table_of_the_wrong_type_is_refused() -> None:
    with pytest.raises(BacktestConfigurationError, match="pandas DataFrame"):
        _measure(residuals="not a frame")

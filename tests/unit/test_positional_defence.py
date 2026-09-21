"""The positional candidate's arithmetic and the three clauses, pinned to their protocol."""

import pandas as pd
import pytest

from squadopt.experiments.positional_defence import (
    CLEAN_SHEET_POINTS,
    MAXIMUM_LOSING_SEASONS,
    ORDERING_TOLERANCE,
    accuracy_clause,
    bonus_by_position,
    candidate_points,
    decision_clause,
    eligible_rows,
    long_indicator,
    ordering_clause,
    positional_defence_gate,
)


def _rows(**overrides: object) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "season": ["2022-23"] * 5,
            "target_gameweek": [4, 4, 4, 4, 3],
            "position": ["GK", "DEF", "DEF", "MID", "DEF"],
            "fixture_count": [1, 1, 2, 1, 1],
            "control_expected_points": [3.0, 2.0, 5.0, 4.0, 2.0],
            "appearance_target": [1, 1, 1, 1, 0],
            "expected_minutes_if_appearance": [88.0, 45.0, 90.0, 80.0, 70.0],
        }
    )
    for name, value in overrides.items():
        frame[name] = value
    return frame


def test_the_population_drops_what_the_protocol_drops_and_counts_each_rule() -> None:
    """Three rules, three counts. A row outside the group or the window never enters."""

    frame = _rows()
    # One `direct_control` row, and it is also a double: the overlap is counted once.
    frame.loc[2, "control_expected_points"] = None
    kept, counts = eligible_rows(frame)
    # The midfielder and the gameweek-3 row are outside the population, not dropped by a rule.
    assert counts.rows_before_drops == 3
    assert counts.direct_control_dropped == 1
    assert counts.double_gameweek_dropped == 1
    assert counts.dropped_by_both == 1
    assert counts.rows == 2 and counts.appeared_rows == 2
    assert list(kept["position"]) == ["GK", "DEF"]


def test_a_club_with_no_fixture_is_dropped_although_the_rule_binds_on_nothing_today() -> None:
    """The archive's judged rows take only one or two fixtures, so this rule is empty there.

    It is implemented anyway. A rule that binds on nothing today and is quietly left out is a
    rule that binds on something tomorrow and is not there.
    """

    frame = _rows()
    frame.loc[1, "fixture_count"] = 0
    _, counts = eligible_rows(frame)
    assert counts.blank_gameweek_dropped == 1
    assert counts.rows == 1


def test_a_missing_minutes_scalar_leaves_long_absent_rather_than_zero() -> None:
    """`NaN >= 60` is False, which would price the row as a certain substitute silently."""

    frame = _rows()
    frame.loc[0, "expected_minutes_if_appearance"] = None
    indicator = long_indicator(frame)
    assert indicator[0] is pd.NA
    # Sixty is inside the threshold, not above it.
    assert list(long_indicator(_rows(expected_minutes_if_appearance=60.0))[:2]) == [1.0, 1.0]
    assert list(long_indicator(_rows(expected_minutes_if_appearance=59.9))[:2]) == [0.0, 0.0]


def test_the_candidate_is_the_protocols_expression_and_refuses_a_missing_factor() -> None:
    frame = pd.DataFrame({"position": ["DEF", "DEF", "GK"], "appearance_probability": [0.5] * 3})
    long = pd.Series([1.0, 0.0, pd.NA], dtype="Float64")
    clean = pd.Series([0.25, 0.25, 0.25], dtype="Float64")
    priced = candidate_points(frame, long, clean, {"DEF": 0.3, "GK": 0.2})
    # A long appearance is paid two points plus four times the clean-sheet chance plus bonus.
    assert priced[0] == pytest.approx(0.5 * (2.0 + CLEAN_SHEET_POINTS * 0.25 + 0.3))
    # A short one is paid one point, and no clean sheet at all: the game pays it at sixty.
    assert priced[1] == pytest.approx(0.5 * (1.0 + 0.3))
    # No `long`, no price. Half a structure is not a number.
    assert priced[2] is pd.NA
    # A position with no fitted bonus is unpriced rather than priced at zero bonus.
    assert candidate_points(frame, long, clean, {"GK": 0.2})[0] is pd.NA


def test_the_bonus_is_a_mean_over_appeared_rows_and_absent_where_nothing_appeared() -> None:
    rows = pd.DataFrame(
        {
            "season": ["2021-22"] * 4 + ["2022-23"],
            "position": ["DEF", "DEF", "DEF", "GK", "DEF"],
            # The third defender did not appear and must not drag the mean toward zero.
            "minutes": [90, 90, 0, 0, 90],
            "bonus": [3, 1, 0, 0, 9],
        }
    )
    means = bonus_by_position(rows, ["2021-22"])
    assert means["DEF"] == pytest.approx(2.0)
    # Goalkeepers have no appeared row in that season, so there is no mean, not a zero.
    assert "GK" not in means
    # The later season is outside the training window and does not reach the mean.
    assert bonus_by_position(rows, ["2021-22"])["DEF"] != pytest.approx(13 / 4)


def _season(candidate: float | None, control: float | None) -> dict[str, float | None]:
    return {"candidate": candidate, "control": control}


def test_the_floor_passes_on_an_exact_tie_and_the_binding_half_needs_every_season() -> None:
    appeared = {"mean_difference": 0.05, "interval": (0.01, 0.09)}
    seasons = {"2022-23": _season(1.0, 1.1), "2023-24": _season(1.0, 1.2)}
    clause = accuracy_clause(appeared, seasons, {"candidate": 2.0, "control": 2.0})
    # Not an improvement, a floor: equality is not a failure.
    assert clause["floor_over_surviving_rows"]["passes"] is True
    assert clause["passes"] is True
    assert (
        accuracy_clause(appeared, seasons, {"candidate": 2.001, "control": 2.0})["passes"] is False
    )

    # One season that does not improve fails the binding half even with a good interval.
    mixed = {**seasons, "2024-25": _season(1.3, 1.2)}
    assert accuracy_clause(appeared, mixed, {"candidate": 2.0, "control": 2.0})["passes"] is False
    # A season that could not be read has not improved; silence is not a pass.
    unread = {**seasons, "2024-25": _season(None, 1.2)}
    assert accuracy_clause(appeared, unread, {"candidate": 2.0, "control": 2.0})["passes"] is False
    # An interval touching zero is not an interval above it.
    touching = {"mean_difference": 0.05, "interval": (0.0, 0.09)}
    assert accuracy_clause(touching, seasons, {"candidate": 2.0, "control": 2.0})["passes"] is False


def _ranks(candidate: float | None, control: float | None) -> dict[str, dict[str, float | None]]:
    return {position: {"candidate": candidate, "control": control} for position in ("GK", "DEF")}


def test_the_ordering_tolerance_is_inclusive_and_an_unreadable_season_fails() -> None:
    # Exactly at the tolerance is inside it, and the arithmetic that produces "exactly" is
    # the arithmetic the clause will meet: 0.50 - 0.010 against 0.50 computes a shortfall of
    # 0.010000000000000009, which is why the clause carries a representation guard.
    inside = {"2022-23": _ranks(0.50 - ORDERING_TOLERANCE, 0.50)}
    assert ordering_clause(inside, _ranks(0.5, 0.5))["passes"] is True
    assert 0.50 - (0.50 - ORDERING_TOLERANCE) > ORDERING_TOLERANCE
    # The guard is for representation and rescues nothing: a thousandth beyond still fails.
    outside = {"2022-23": _ranks(0.50 - ORDERING_TOLERANCE - 0.001, 0.50)}
    assert ordering_clause(outside, _ranks(0.5, 0.5))["passes"] is False
    # A pooled shortfall beyond the tolerance fails even when every season is inside it.
    assert ordering_clause(inside, _ranks(0.4, 0.5))["passes"] is False
    # Ordering better than the control is never a failure.
    assert ordering_clause({"2022-23": _ranks(0.9, 0.5)}, _ranks(0.9, 0.5))["passes"] is True
    assert ordering_clause({"2022-23": _ranks(None, 0.5)}, _ranks(0.5, 0.5))["passes"] is False


def test_the_decision_clause_allows_one_losing_season_and_the_interval_does_not_gate() -> None:
    means = {"2022-23": 1.0, "2023-24": -0.5, "2024-25": 2.0}
    clause = decision_clause(0.8, means, (-5.0, 6.0), 104)
    assert clause["losing_seasons"] == ["2023-24"]
    assert clause["passes"] is True
    # The interval is wide and straddles zero, and the clause still passes: it is reported.
    assert clause["interval_gates"] is False
    assert MAXIMUM_LOSING_SEASONS == 1

    two_losing = {"2022-23": -1.0, "2023-24": -0.5, "2024-25": 2.0}
    assert decision_clause(0.1, two_losing, None, 104)["passes"] is False
    # A mean below zero fails whatever the seasons did.
    assert decision_clause(-0.001, means, None, 104)["passes"] is False
    # Exactly zero is at least zero.
    assert decision_clause(0.0, means, None, 104)["passes"] is True


def test_the_gate_needs_all_three_and_names_the_ones_that_failed() -> None:
    passing = {"passes": True}
    failing = {"passes": False}
    assert positional_defence_gate(passing, passing, passing)["verdict"] == "passes"
    verdict = positional_defence_gate(passing, failing, failing)
    assert verdict["verdict"] == "fails"
    assert verdict["failing_clauses"] == ["decision", "ordering"]

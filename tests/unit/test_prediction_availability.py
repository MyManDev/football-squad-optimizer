"""Tests for applying captured availability as a rule rather than a feature."""

from typing import Any

import pandas as pd
import pytest

from squadopt.prediction.availability import (
    KNOWN_STATUSES,
    UNAVAILABLE_STATUSES,
    AvailabilityRuleConfig,
    apply_availability,
)
from squadopt.prediction.config import PredictionConfigurationError


def _projection(points: float = 4.0, players: int = 1) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"player_id": index, "name": f"P{index}", "expected_points": points}
            for index in range(1, players + 1)
        ]
    )


def _availability(rows: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=["player_id", "status", "chance_of_playing"])
    frame["player_id"] = frame["player_id"].astype("int64")
    frame["status"] = frame["status"].astype("string")
    frame["chance_of_playing"] = frame["chance_of_playing"].astype("Int64")
    return frame


def _record(status: str = "a", chance: object = pd.NA, player_id: int = 1) -> dict[str, Any]:
    return {"player_id": player_id, "status": status, "chance_of_playing": chance}


# --- the rule ---------------------------------------------------------------


def test_an_available_player_is_untouched() -> None:
    adjustment = apply_availability(_projection(), _availability([_record("a")]))

    assert adjustment.table["expected_points"].tolist() == [4.0]
    assert adjustment.multiplier.tolist() == [1.0]


@pytest.mark.parametrize("status", UNAVAILABLE_STATUSES)
def test_an_unavailable_status_zeroes_the_projection(status: str) -> None:
    adjustment = apply_availability(_projection(), _availability([_record(status)]))

    assert adjustment.table["expected_points"].tolist() == [0.0]
    assert adjustment.unavailable_players == (1,)


def test_a_stated_chance_scales_the_projection() -> None:
    adjustment = apply_availability(_projection(), _availability([_record("d", 75)]))

    assert adjustment.table["expected_points"].tolist() == [pytest.approx(3.0)]


def test_a_stated_chance_takes_precedence_over_the_status() -> None:
    """The chance is the more specific claim; the source states it deliberately."""

    adjustment = apply_availability(_projection(), _availability([_record("i", 100)]))

    assert adjustment.table["expected_points"].tolist() == [4.0]


def test_a_stated_zero_chance_zeroes_an_otherwise_available_player() -> None:
    adjustment = apply_availability(_projection(), _availability([_record("a", 0)]))

    assert adjustment.table["expected_points"].tolist() == [0.0]
    assert adjustment.unavailable_players == (1,)


def test_doubtful_without_a_chance_is_read_as_half() -> None:
    """The source signalled uncertainty without quantifying it."""

    adjustment = apply_availability(_projection(), _availability([_record("d")]))

    assert adjustment.table["expected_points"].tolist() == [pytest.approx(2.0)]


def test_an_unrecognised_status_stops_the_run() -> None:
    """A wrong guess about the most common status would misprice the whole roster."""

    with pytest.raises(PredictionConfigurationError, match="not one of"):
        apply_availability(_projection(), _availability([_record("x")]))


def test_the_known_vocabulary_is_declared() -> None:
    assert set(KNOWN_STATUSES) == {"a", "d", *UNAVAILABLE_STATUSES}


# --- players the capture says nothing about ---------------------------------


def test_a_player_without_a_record_is_treated_as_available() -> None:
    """Silence is the normal state; reading it as doubt penalises the unremarkable."""

    adjustment = apply_availability(
        _projection(players=2), _availability([_record("a", player_id=1)])
    )

    assert adjustment.table["expected_points"].tolist() == [4.0, 4.0]
    assert adjustment.diagnostics["availability_players_unmatched"] == 1


def test_the_default_can_be_inverted() -> None:
    adjustment = apply_availability(
        _projection(players=2),
        _availability([_record("a", player_id=1)]),
        config=AvailabilityRuleConfig(unknown_is_available=False),
    )

    assert adjustment.table["expected_points"].tolist() == [4.0, 0.0]


# --- the floor --------------------------------------------------------------


def test_the_floor_bounds_how_far_a_projection_can_be_reduced() -> None:
    adjustment = apply_availability(
        _projection(),
        _availability([_record("i", 0)]),
        config=AvailabilityRuleConfig(doubtful_multiplier_floor=0.25),
    )

    assert adjustment.table["expected_points"].tolist() == [pytest.approx(1.0)]


def test_a_chance_above_full_cannot_raise_a_projection() -> None:
    adjustment = apply_availability(_projection(), _availability([_record("a", 150)]))

    assert adjustment.table["expected_points"].tolist() == [4.0]


# --- reporting --------------------------------------------------------------


def test_unavailable_players_are_reported_rather_than_removed() -> None:
    """Dropping rows here could turn a squad infeasible for reasons unseen downstream."""

    adjustment = apply_availability(
        _projection(players=2),
        _availability([_record("i", 0, player_id=1), _record("a", player_id=2)]),
    )

    assert len(adjustment.table) == 2
    assert adjustment.unavailable_players == (1,)


def test_the_diagnostics_count_what_the_rule_did() -> None:
    adjustment = apply_availability(
        _projection(players=3),
        _availability(
            [
                _record("a", player_id=1),
                _record("d", 75, player_id=2),
                _record("i", 0, player_id=3),
            ]
        ),
    )

    assert adjustment.diagnostics["availability_players_matched"] == 3
    assert adjustment.diagnostics["availability_chance_stated"] == 2
    assert adjustment.diagnostics["availability_unavailable"] == 1
    assert adjustment.diagnostics["availability_reduced"] == 1


def test_the_diagnostics_are_read_only() -> None:
    adjustment = apply_availability(_projection(), _availability([_record("a")]))

    with pytest.raises(TypeError):
        adjustment.diagnostics["availability_unavailable"] = 5  # type: ignore[index]


def test_a_halved_projection_is_visible_as_such() -> None:
    """A quietly halved projection is indistinguishable from a model that predicted half."""

    adjustment = apply_availability(_projection(), _availability([_record("d", 50)]))

    assert adjustment.multiplier.tolist() == [pytest.approx(0.5)]


# --- input handling ---------------------------------------------------------


def test_the_inputs_are_not_modified() -> None:
    projection = _projection()
    availability = _availability([_record("d", 75)])
    before_projection = projection.copy(deep=True)
    before_availability = availability.copy(deep=True)

    apply_availability(projection, availability)

    assert projection.equals(before_projection)
    assert availability.equals(before_availability)


def test_a_repeated_player_in_the_availability_table_is_rejected() -> None:
    with pytest.raises(PredictionConfigurationError, match="repeats player_id"):
        apply_availability(_projection(), _availability([_record("a"), _record("i", 0)]))


def test_a_missing_expected_points_value_is_rejected() -> None:
    projection = _projection()
    projection.loc[0, "expected_points"] = pd.NA

    with pytest.raises(PredictionConfigurationError, match="must be present"):
        apply_availability(projection, _availability([_record("a")]))


@pytest.mark.parametrize("column", ["player_id", "expected_points"])
def test_a_projection_missing_a_required_column_is_rejected(column: str) -> None:
    projection = _projection().drop(columns=[column])

    with pytest.raises(PredictionConfigurationError, match=column):
        apply_availability(projection, _availability([_record("a")]))


@pytest.mark.parametrize("column", ["status", "chance_of_playing"])
def test_an_availability_table_missing_a_column_is_rejected(column: str) -> None:
    availability = _availability([_record("a")]).drop(columns=[column])

    with pytest.raises(PredictionConfigurationError, match=column):
        apply_availability(_projection(), availability)


@pytest.mark.parametrize("floor", [-0.1, 1.1, float("nan"), True])
def test_an_invalid_floor_is_rejected(floor: object) -> None:
    with pytest.raises(PredictionConfigurationError, match="doubtful_multiplier_floor"):
        AvailabilityRuleConfig(doubtful_multiplier_floor=floor)  # type: ignore[arg-type]


def test_the_config_is_immutable() -> None:
    config = AvailabilityRuleConfig()

    with pytest.raises(AttributeError):
        config.unknown_is_available = False  # type: ignore[misc]


# --- the appearance chance the rule is news about ---------------------------


def test_the_chance_of_appearing_is_scaled_by_the_same_multiplier() -> None:
    """This rule is news about appearing, so it belongs in both numbers or neither.

    A stated chance of playing is a chance of appearing and an injured status is the
    claim that the player will not, so a rule that moved only the points would leave
    behind an appearance probability from before the news.
    """

    projection = _projection().assign(appearance_probability=0.8)

    adjusted = apply_availability(projection, _availability([_record("d", 25)]))

    assert adjusted.table.loc[0, "expected_points"] == pytest.approx(1.0)
    assert adjusted.table.loc[0, "appearance_probability"] == pytest.approx(0.2)


def test_the_composition_survives_this_step() -> None:
    """The property the bench rule of #531 rests on.

    The component producer composes ``expected_points = appearance_probability *
    points_if_appearance``, and the bench is ordered by the quotient of the two. Scale
    one side only and the quotient stops being the conditional mean either number meant:
    a player doubtful at a quarter would be ordered at a quarter of what they are worth
    *if* they play, which is the one thing the exchange argument says must not happen.
    """

    conditional = 5.0
    projection = _projection(points=0.8 * conditional).assign(appearance_probability=0.8)

    table = apply_availability(projection, _availability([_record("d", 25)])).table
    quotient = table.loc[0, "expected_points"] / table.loc[0, "appearance_probability"]

    assert quotient == pytest.approx(conditional)


def test_a_projection_that_states_no_chance_is_left_exactly_as_it_is() -> None:
    """Every producer but the component one is on this path and must not move."""

    adjusted = apply_availability(_projection(), _availability([_record("d", 25)]))

    assert "appearance_probability" not in adjusted.table.columns


def test_an_unmodelled_player_keeps_its_absence_through_the_rule() -> None:
    """Absent is not zero here either: scaling nothing must not produce a number."""

    projection = _projection(players=2).assign(appearance_probability=[0.8, None])

    table = apply_availability(
        projection, _availability([_record("d", 25, 1), _record("d", 25, 2)])
    ).table

    assert table.loc[0, "appearance_probability"] == pytest.approx(0.2)
    assert pd.isna(table.loc[1, "appearance_probability"])


def test_an_unavailable_player_reaches_zero_on_both_numbers() -> None:
    projection = _projection().assign(appearance_probability=0.9)

    table = apply_availability(projection, _availability([_record("i")])).table

    assert table.loc[0, "expected_points"] == pytest.approx(0.0)
    assert table.loc[0, "appearance_probability"] == pytest.approx(0.0)

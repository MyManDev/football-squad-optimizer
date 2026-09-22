"""The projection contract's optional tier: carried when supplied, never invented.

A required column means every producer must supply it, so putting a start probability there
would turn a projection without one into an error and leave a member whose week nobody
modelled with no plan at all. The optional tier is the shape `data/schema` has carried one
layer down since it was written -- required, optional, canonical, and "absent fields are never
fabricated" -- now that the projection needs it too.

What these hold: the tier's own invariants, that a frame carrying an optional column keeps it
all the way to the solve, that a frame without one narrows exactly as it did before, and that
an absent value stays absent rather than becoming a zero.
"""

import pandas as pd
import pytest

from squadopt import OptimizationConfig
from squadopt.contracts import (
    CANONICAL_COLUMNS,
    OPTIONAL_COLUMNS,
    REQUIRED_COLUMNS,
    canonical_columns_present,
    order_outfield_bench,
)
from squadopt.optimization.validation import validate_players
from squadopt.prediction import PredictionConfigurationError
from squadopt.prediction.integration import (
    PredictionProvenance,
    PredictionSnapshot,
    _prediction_fingerprint,
)

PROVENANCE = PredictionProvenance(
    model_name="optional-tier",
    model_version="v1",
    feature_contract_version="features-v1",
    training_cutoff="2024-25:GW38",
    training_data_fingerprint="a" * 64,
)


def _table(**extra: object) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "player_id": [1, 2, 3],
            "name": ["Keeper", "Back", "Wing"],
            "team_id": [10, 11, 12],
            "position": ["GK", "DEF", "MID"],
            "price_tenths": [45, 50, 75],
            "expected_points": [2.5, 3.5, 5.0],
        }
    )
    for column, values in extra.items():
        frame[column] = values
    return frame


def _snapshot(table: pd.DataFrame) -> PredictionSnapshot:
    return PredictionSnapshot(
        table=table,
        provenance=PROVENANCE,
        prediction_fingerprint=_prediction_fingerprint(table, PROVENANCE),
    )


# --- the tier itself --------------------------------------------------------


def test_the_two_tiers_do_not_overlap_and_canonical_is_their_concatenation() -> None:
    assert not set(REQUIRED_COLUMNS) & set(OPTIONAL_COLUMNS)
    assert (*REQUIRED_COLUMNS, *OPTIONAL_COLUMNS) == CANONICAL_COLUMNS
    assert set(OPTIONAL_COLUMNS) == {"appearance_probability", "start_probability"}


def test_a_frame_without_an_optional_column_narrows_exactly_as_before() -> None:
    """The absence path is the one every producer is on today, and it must not move."""

    assert canonical_columns_present(_table()) == list(REQUIRED_COLUMNS)


def test_an_optional_column_is_carried_and_an_unknown_one_is_not() -> None:
    frame = _table(start_probability=[0.9, 0.4, 0.7], points_last_5=[1, 2, 3])

    assert canonical_columns_present(frame) == [*REQUIRED_COLUMNS, "start_probability"]


def test_the_appearance_chance_is_in_the_tier_and_narrows_in_contract_order() -> None:
    """The column the bench rule needs (#531), and the one a producer fills today.

    Order is the contract's rather than the frame's, so a producer that happens to build its
    columns the other way round still narrows to the same shape.
    """

    frame = _table(start_probability=[0.5] * 3, appearance_probability=[0.9, 0.4, 0.7])

    assert canonical_columns_present(frame) == [*REQUIRED_COLUMNS, *OPTIONAL_COLUMNS]


# --- the boundary the column has to cross -----------------------------------


def test_a_supplied_appearance_probability_survives_the_projection_boundary() -> None:
    """The boundary #621's task 4.1 is about: the producer fills it and the solve sees it."""

    snapshot = _snapshot(_table(appearance_probability=[0.95, 0.40, 0.72]))

    assert list(snapshot.table.columns) == [*REQUIRED_COLUMNS, "appearance_probability"]
    assert snapshot.table["appearance_probability"].tolist() == [0.95, 0.40, 0.72]


def test_an_appearance_chance_nobody_estimated_stays_absent() -> None:
    """Absent is not zero, and here the difference is a bench order.

    Ordering the bench by ``expected_points / appearance_probability`` reads a zero as a
    division by zero rather than as "nobody modelled this player", so the absence has to
    arrive as an absence.
    """

    snapshot = _snapshot(_table(appearance_probability=[0.95, None, 0.72]))

    assert snapshot.table["appearance_probability"].isna().tolist() == [False, True, False]


def test_a_supplied_start_probability_survives_the_projection_boundary() -> None:
    """Before this tier the boundary narrowed to six columns and the seventh never arrived."""

    snapshot = _snapshot(_table(start_probability=[0.95, 0.40, 0.72]))

    assert list(snapshot.table.columns) == [*REQUIRED_COLUMNS, "start_probability"]
    assert snapshot.table["start_probability"].tolist() == [0.95, 0.40, 0.72]


def test_a_start_probability_nobody_estimated_stays_absent() -> None:
    """Absent is not zero: a model with no opinion about a player must be able to say so.

    A rule that refused the missing value here would make the optional column a required one
    with extra steps, and a consumer reading the absence as zero would bench every player
    nobody modelled -- a larger change than supplying the column at all, in the wrong
    direction.
    """

    snapshot = _snapshot(_table(start_probability=[0.95, None, 0.72]))

    assert snapshot.table["start_probability"].isna().tolist() == [False, True, False]


def test_a_missing_value_in_a_required_column_is_still_refused() -> None:
    """The exemption is the optional tier's, and it is not a hole in the required one."""

    with pytest.raises(PredictionConfigurationError, match="missing values"):
        _snapshot(_table().assign(expected_points=[2.5, None, 5.0]))


def test_an_unrecognised_column_does_not_cross_the_boundary() -> None:
    snapshot = _snapshot(_table(points_last_5=[1, 2, 3]))

    assert "points_last_5" not in snapshot.table.columns


# --- what the optional column must not disturb ------------------------------


def test_the_prediction_fingerprint_does_not_move_when_one_is_supplied() -> None:
    """Provenance identity is the six agreed fields; an optional column cannot restate it."""

    assert _prediction_fingerprint(_table(start_probability=[0.9, 0.4, 0.7]), PROVENANCE) == (
        _prediction_fingerprint(_table(), PROVENANCE)
    )


def test_the_optimizer_accepts_a_pool_that_carries_one() -> None:
    """The consumer's own validator, which is the strongest check available here.

    A pool the optimizer would actually accept: fifteen is the squad, so a smaller frame
    refuses for a reason that has nothing to do with the column under test.
    """

    positions = ["GK", "GK", *["DEF"] * 6, *["MID"] * 6, *["FWD"] * 6]
    pool = pd.DataFrame(
        {
            "player_id": range(1, len(positions) + 1),
            "name": [f"Player {index}" for index in range(1, len(positions) + 1)],
            "team_id": [index % 10 + 1 for index in range(len(positions))],
            "position": positions,
            "price_tenths": [45 + index for index in range(len(positions))],
            "expected_points": [2.0 + index * 0.1 for index in range(len(positions))],
            "start_probability": [0.5 + index * 0.02 for index in range(len(positions))],
        }
    )

    validated = validate_players(pool, OptimizationConfig())

    assert "start_probability" in validated.columns


# --- the bench that reads it ------------------------------------------------


def _bench(
    points: list[float], chances: list[object] | None = None, **extra: object
) -> pd.DataFrame:
    frame = pd.DataFrame({"player_id": [10, 20, 30], "expected_points": points})
    if chances is not None:
        frame["appearance_probability"] = chances
    for column, values in extra.items():
        frame[column] = values
    return frame


def _order(frame: pd.DataFrame) -> list[int]:
    return [int(value) for value in order_outfield_bench(frame)["player_id"].tolist()]


def test_the_bench_is_ordered_by_points_given_an_appearance() -> None:
    """The two orders disagree here, which is the only way to see which one ran.

    By total the order is 30, 20, 10. Given an appearance it is 10, 20, 30: the player
    worth 1.0 with a one-in-ten chance is worth 10 if he turns up, and the bench costs
    nothing when he does not.
    """

    frame = _bench([1.0, 2.0, 3.0], [0.1, 0.5, 0.9])

    assert _order(frame) == [10, 20, 30]
    assert _order(frame.drop(columns="appearance_probability")) == [30, 20, 10]


def test_a_bench_with_no_chance_column_orders_exactly_as_it_did_before() -> None:
    assert _order(_bench([1.0, 3.0, 2.0])) == [20, 30, 10]


def test_one_unmodelled_row_sends_the_whole_bench_back_to_the_old_rule() -> None:
    """The decision this rests on, built so per-row and whole-bench disagree.

    Per row, player 10 would divide to 4.0 and lead. Whole bench, the old order stands
    and player 30 leads on 3.0. Per row is not "use what is available": it is reading the
    absent chance as one, and the absence means nobody modelled that player.
    """

    frame = _bench([2.0, 1.0, 3.0], [0.5, 0.5, None])

    assert _order(frame) == [30, 10, 20]


def test_a_blank_gameweek_row_does_not_divide_by_zero() -> None:
    """``_compose`` writes zero into every number of a no-fixture row, both of them."""

    frame = _bench([0.0, 2.0, 3.0], [0.0, 0.5, 0.9])

    assert _order(frame) == [30, 20, 10]


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -0.5, "0.8", True, None])
def test_a_chance_that_cannot_be_divided_by_is_a_fallback_not_a_raise(bad: object) -> None:
    assert _order(_bench([1.0, 3.0, 2.0], [bad, 0.5, 0.5])) == [20, 30, 10]


def test_a_chance_above_one_is_used_rather_than_refused() -> None:
    """Nothing validates this column, so a sort cannot tell wrong from implausible.

    Refusing 1.2 would tie a frozen bench order to a threshold no contract declares, and
    would hide a producer defect inside a sort instead of surfacing it in the producer.
    """

    frame = _bench([3.0, 2.0, 1.0], [1.2, 0.5, 0.9])

    # 3.0/1.2 = 2.5, 2.0/0.5 = 4.0, 1.0/0.9 = 1.11. Falling back would have given 10, 20, 30.
    assert _order(frame) == [20, 10, 30]


def test_an_exact_tie_is_broken_by_the_identifier() -> None:
    frame = _bench([1.0, 2.0, 3.0], [0.5, 1.0, 1.5])

    assert _order(frame) == [10, 20, 30]


def test_a_text_identifier_sorts_after_a_number_without_raising() -> None:
    """``PlanningHorizon`` permits a text id, and a bench order must not depend on luck."""

    frame = pd.DataFrame({"player_id": ["b", 7, "a"], "expected_points": [2.0, 2.0, 2.0]})

    assert [str(value) for value in order_outfield_bench(frame)["player_id"]] == ["7", "a", "b"]


@pytest.mark.parametrize("rows", [0, 1])
def test_an_empty_or_single_bench_returns_without_raising(rows: int) -> None:
    frame = pd.DataFrame(
        {
            "player_id": [10][:rows],
            "expected_points": [1.0][:rows],
            "appearance_probability": [0.5][:rows],
        }
    )

    assert len(order_outfield_bench(frame)) == rows


def test_the_input_frame_is_left_alone_and_the_answer_is_independent() -> None:
    frame = _bench([1.0, 2.0, 3.0], [0.1, 0.5, 0.9])
    before = frame.copy(deep=True)

    ordered = order_outfield_bench(frame)
    ordered.loc[0, "expected_points"] = 99.0

    assert frame.equals(before)
    assert list(ordered.index) == [0, 1, 2]

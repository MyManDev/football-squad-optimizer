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
    assert "p_start" in OPTIONAL_COLUMNS


def test_a_frame_without_an_optional_column_narrows_exactly_as_before() -> None:
    """The absence path is the one every producer is on today, and it must not move."""

    assert canonical_columns_present(_table()) == list(REQUIRED_COLUMNS)


def test_an_optional_column_is_carried_and_an_unknown_one_is_not() -> None:
    frame = _table(p_start=[0.9, 0.4, 0.7], points_last_5=[1, 2, 3])

    assert canonical_columns_present(frame) == [*REQUIRED_COLUMNS, "p_start"]


# --- the boundary the column has to cross -----------------------------------


def test_a_supplied_start_probability_survives_the_projection_boundary() -> None:
    """Before this tier the boundary narrowed to six columns and the seventh never arrived."""

    snapshot = _snapshot(_table(p_start=[0.95, 0.40, 0.72]))

    assert list(snapshot.table.columns) == [*REQUIRED_COLUMNS, "p_start"]
    assert snapshot.table["p_start"].tolist() == [0.95, 0.40, 0.72]


def test_a_start_probability_nobody_estimated_stays_absent() -> None:
    """Absent is not zero: a model with no opinion about a player must be able to say so.

    A rule that refused the missing value here would make the optional column a required one
    with extra steps, and a consumer reading the absence as zero would bench every player
    nobody modelled -- a larger change than supplying the column at all, in the wrong
    direction.
    """

    snapshot = _snapshot(_table(p_start=[0.95, None, 0.72]))

    assert snapshot.table["p_start"].isna().tolist() == [False, True, False]


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

    assert _prediction_fingerprint(_table(p_start=[0.9, 0.4, 0.7]), PROVENANCE) == (
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
            "p_start": [0.5 + index * 0.02 for index in range(len(positions))],
        }
    )

    validated = validate_players(pool, OptimizationConfig())

    assert "p_start" in validated.columns

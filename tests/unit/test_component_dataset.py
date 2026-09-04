"""Tests for the leakage-safe modelling frame.

Two invariants carry the whole leakage argument for the development folds, and neither is
checkable by reading a number off the output: the feature set is an allowlist of columns
whose time of knowledge is declared, and a training slice stops strictly before the
decision it will be scored against. Both are asserted here.
"""

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from squadopt.data.schema import (
    AMBIGUOUS_TIMING_COLUMNS,
    DERIVED_OUTCOME_COLUMNS,
    KEY_COLUMNS,
    OUTCOME_COLUMNS,
)
from squadopt.features.component_targets import build_component_targets
from squadopt.features.config import feature_column_names
from squadopt.features.evidence import EVIDENCE_COLUMNS
from squadopt.prediction.component_dataset import (
    COMPONENT_FEATURE_CONFIG,
    DATASET_CONTRACT_VERSION,
    FEATURE_CONTRACT_VERSION,
    PRE_MATCH_FEATURE_COLUMNS,
    build_component_frame,
    component_feature_columns,
    excluded_ratio_features,
    rows_at,
    rows_strictly_before,
)
from squadopt.prediction.config import PredictionConfigurationError

SEASON_ORDER = ("2023-24", "2024-25")
FEATURES = component_feature_columns()


def _features(rows: list[tuple[str, int, int]]) -> pd.DataFrame:
    """A feature frame from (season, gameweek, player_id); every feature is present."""

    frame = pd.DataFrame(
        {
            "season": pd.Series([row[0] for row in rows], dtype="string"),
            "gameweek": pd.Series([row[1] for row in rows], dtype="int64"),
            "player_id": pd.Series([row[2] for row in rows], dtype="int64"),
        }
    )
    for offset, column in enumerate(FEATURES, start=1):
        frame[column] = pd.Series([float(offset)] * len(rows), dtype="float64")
    return frame


def _panel(rows: list[tuple[str, int, int, int, int]]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "season": pd.Series([row[0] for row in rows], dtype="string"),
            "gameweek": pd.Series([row[1] for row in rows], dtype="int64"),
            "player_id": pd.Series([row[2] for row in rows], dtype="int64"),
            "name": pd.Series([f"P{row[2]}" for row in rows], dtype="string"),
            "team_id": pd.Series([1] * len(rows), dtype="int64"),
            "position": pd.Series(["MID"] * len(rows), dtype="string"),
            "price_tenths": pd.Series([50] * len(rows), dtype="int64"),
            "minutes": pd.Series([row[3] for row in rows], dtype="int64"),
            "total_points": pd.Series([row[4] for row in rows], dtype="int64"),
        }
    )


# --- the allowlist ----------------------------------------------------------


def test_no_feature_column_carries_outcome_or_unproven_timing() -> None:
    """The structural check the whole leakage argument rests on.

    Stated as a set intersection rather than a list of names, so a column added to the
    schema's outcome or ambiguous-timing tuples is caught here without this test being
    edited. A shifted rolling aggregate *of* an outcome is legal and is not in those
    tuples; the raw outcome is, and is what must never appear.
    """

    forbidden = {*OUTCOME_COLUMNS, *DERIVED_OUTCOME_COLUMNS, *AMBIGUOUS_TIMING_COLUMNS}

    assert set(FEATURES) & forbidden == set()


def test_selected_by_percent_is_excluded_although_the_panel_publishes_it() -> None:
    """It is real, present, and its snapshot timing is unproven, which is what rules it out."""

    assert "selected_by_percent" in AMBIGUOUS_TIMING_COLUMNS
    assert "selected_by_percent" not in FEATURES


def test_the_feature_order_is_fixed() -> None:
    """A design matrix in another column order is another model, silently."""

    assert component_feature_columns() == FEATURES
    assert FEATURES[-3:] == ("price_tenths", "fixture_count", "home_fixture_count")


def test_every_rolling_feature_name_is_one_the_configuration_produces() -> None:
    """The allowlist is assembled by hand, so a typo would name a column that never exists.

    Checking it against `feature_column_names` is what makes the hand-assembly safe: the
    set may be a subset, never a name the builder does not write.
    """

    produced = set(feature_column_names(COMPONENT_FEATURE_CONFIG))
    rolling = [column for column in FEATURES if column not in PRE_MATCH_FEATURE_COLUMNS]

    assert rolling
    assert set(rolling) <= produced


def test_the_excluded_features_are_exactly_the_undefined_ratios() -> None:
    """They divide by a window's appearances, so they do not exist for a player with none.

    Measured on 2024-25: 45 to 49 per cent of rows, against 2.9 per cent for the genuine
    no-history case. Requiring them would drop half the population; imputing them would
    put a number where the quantity is undefined.
    """

    assert excluded_ratio_features() == (
        "points_per_90_last_5",
        "minutes_per_appearance_last_3",
        "minutes_per_appearance_last_5",
    )
    assert set(excluded_ratio_features()) & set(FEATURES) == set()


def test_the_contract_versions_are_declared() -> None:
    assert DATASET_CONTRACT_VERSION == "phase_c_component_dataset_v1"
    assert FEATURE_CONTRACT_VERSION == "phase_c_component_form_window_v1"


# --- the join ---------------------------------------------------------------


def test_features_and_targets_join_on_the_canonical_key() -> None:
    rows = [("2024-25", 1, 1), ("2024-25", 2, 1)]
    targets = build_component_targets(_panel([("2024-25", 1, 1, 0, 0), ("2024-25", 2, 1, 90, 7)]))

    frame = build_component_frame(_features(rows), targets)

    assert len(frame) == 2
    assert frame["appearance_target"].tolist() == [0, 1]
    assert list(frame.columns[: len(KEY_COLUMNS)]) == list(KEY_COLUMNS)


def test_a_feature_row_with_no_target_is_not_a_modelling_row() -> None:
    targets = build_component_targets(_panel([("2024-25", 1, 1, 90, 6)]))

    frame = build_component_frame(_features([("2024-25", 1, 1), ("2024-25", 2, 1)]), targets)

    assert len(frame) == 1
    assert frame["gameweek"].tolist() == [1]


def test_the_inputs_are_not_modified() -> None:
    features = _features([("2024-25", 1, 1)])
    targets = build_component_targets(_panel([("2024-25", 1, 1, 90, 6)]))
    before_features, before_targets = features.copy(deep=True), targets.copy(deep=True)

    build_component_frame(features, targets)

    assert_frame_equal(features, before_features)
    assert_frame_equal(targets, before_targets)


def test_a_missing_feature_column_is_refused_rather_than_filled() -> None:
    targets = build_component_targets(_panel([("2024-25", 1, 1, 90, 6)]))
    features = _features([("2024-25", 1, 1)]).drop(columns=["points_last_5"])

    with pytest.raises(PredictionConfigurationError, match="missing columns"):
        build_component_frame(features, targets)


# --- the chronological boundary ---------------------------------------------


def test_a_training_slice_stops_strictly_before_its_own_gameweek() -> None:
    """The decision's own gameweek is what the model will be scored on."""

    frame = _features([("2024-25", 1, 1), ("2024-25", 2, 1), ("2024-25", 3, 1)])

    earlier = rows_strictly_before(frame, season_order=SEASON_ORDER, season="2024-25", gameweek=2)

    assert earlier["gameweek"].tolist() == [1]


def test_an_earlier_season_is_history_and_a_later_one_is_not() -> None:
    frame = _features([("2023-24", 38, 1), ("2024-25", 1, 1), ("2024-25", 2, 1)])

    earlier = rows_strictly_before(frame, season_order=SEASON_ORDER, season="2024-25", gameweek=1)

    assert earlier["season"].tolist() == ["2023-24"]


def test_the_same_players_later_row_never_enters_an_earlier_fold() -> None:
    """Stated at player grain because that is the leak a chronological split exists to stop."""

    frame = _features([("2024-25", 1, 7), ("2024-25", 5, 7), ("2024-25", 9, 7)])

    earlier = rows_strictly_before(frame, season_order=SEASON_ORDER, season="2024-25", gameweek=5)

    assert earlier["gameweek"].tolist() == [1]
    assert 9 not in earlier["gameweek"].tolist()


def test_a_season_the_order_does_not_name_is_refused() -> None:
    """An unranked season sorted quietly to the end is a leak with a plausible cause."""

    frame = _features([("2022-23", 1, 1), ("2024-25", 1, 1)])

    with pytest.raises(PredictionConfigurationError, match="absent from season_order"):
        rows_strictly_before(frame, season_order=SEASON_ORDER, season="2024-25", gameweek=1)


def test_rows_at_returns_exactly_one_decisions_population() -> None:
    frame = _features([("2024-25", 1, 1), ("2024-25", 2, 1), ("2024-25", 2, 2)])

    decision = rows_at(frame, season="2024-25", gameweek=2)

    assert decision["player_id"].tolist() == [1, 2]


def test_the_slices_do_not_modify_the_frame_they_read() -> None:
    frame = _features([("2024-25", 1, 1), ("2024-25", 2, 1)])
    before = frame.copy(deep=True)

    rows_strictly_before(frame, season_order=SEASON_ORDER, season="2024-25", gameweek=2)
    rows_at(frame, season="2024-25", gameweek=2)

    assert_frame_equal(frame, before)


# --- the Phase B boundary, checked but not crossed --------------------------


def test_the_phase_b_evidence_key_maps_onto_this_frames_key() -> None:
    """Evidence is not joined in this contract, only proven joinable later.

    The evidence table names the decision week ``target_gameweek``; the panel names it
    ``gameweek``. Checking the correspondence now is what stops the first candidate run
    from discovering that the two grains never lined up.
    """

    evidence_key = ("season", "target_gameweek", "player_id")

    assert all(column in EVIDENCE_COLUMNS for column in evidence_key)
    assert (
        tuple("gameweek" if column == "target_gameweek" else column for column in evidence_key)
        == KEY_COLUMNS
    )


def test_no_evidence_column_leaks_into_the_control_feature_set() -> None:
    """The control arm must reproduce with no optional evidence at all."""

    optional = {column for column in EVIDENCE_COLUMNS if column.startswith("elite_")}

    assert set(FEATURES) & optional == set()
    assert "overall_selected_by_percent" not in FEATURES

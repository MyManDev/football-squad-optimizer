"""Tests for the Phase C component targets.

The interesting behaviour here is what the builder *refuses* to produce. Three of the four
labels are arithmetic on realized outcomes and hard to get wrong; the fourth does not exist
in this panel, and the tests that matter are the ones pinning it as missing rather than
letting a plausible proxy stand in for it.
"""

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from squadopt.data.errors import DuplicateRecordsError
from squadopt.features.component_targets import (
    COMPONENT_TARGET_COLUMNS,
    START_SOURCE_COLUMN,
    START_TARGET_SUPPORTED_SEASONS,
    TARGET_CONTRACT_VERSION,
    build_component_targets,
)
from squadopt.features.config import FeatureConfigurationError


def _panel(rows: list[tuple[str, int, int, int, int]]) -> pd.DataFrame:
    """Build a canonical panel from (season, gameweek, player_id, minutes, points)."""

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


# --- appearance -------------------------------------------------------------


def test_appearance_is_any_minute_not_a_meaningful_contribution() -> None:
    """One minute is an appearance. The boundary is at zero, not at some playing time."""

    targets = build_component_targets(_panel([("2024-25", 1, 1, 0, 0), ("2024-25", 1, 2, 1, 0)]))

    assert targets.loc[targets["player_id"] == 1, "appearance_target"].tolist() == [0]
    assert targets.loc[targets["player_id"] == 2, "appearance_target"].tolist() == [1]


def test_appearance_is_never_missing() -> None:
    """It is the one unconditional label, so a missing value would be a defect."""

    targets = build_component_targets(_panel([("2024-25", 1, 1, 0, -1), ("2024-25", 2, 1, 90, 8)]))

    assert not bool(targets["appearance_target"].isna().any())


# --- start, which is unavailable --------------------------------------------


def test_the_start_target_is_missing_because_no_season_supports_it() -> None:
    """The pre-registration admits only a verified `starts` indicator, and the archive
    adapter maps none, so the supported-season set is empty and every start label is
    missing rather than zero."""

    assert START_TARGET_SUPPORTED_SEASONS == ()

    targets = build_component_targets(_panel([("2024-25", 1, 1, 90, 6)]))

    assert bool(targets["start_target"].isna().all())
    assert str(targets["start_target"].dtype) == "Int64"


def test_a_present_starts_column_does_not_enable_the_start_target() -> None:
    """What is missing is the declared population, not only the column.

    A live capture does publish `starts`. If its mere presence switched the label on, the
    target would silently exist for some inputs and not others, and the model fitted on it
    would have a population nobody declared. Declaring one is a pre-registration act.
    """

    panel = _panel([("2024-25", 1, 1, 90, 6)]).assign(
        **{START_SOURCE_COLUMN: pd.Series([1], dtype="int64")}
    )

    targets = build_component_targets(panel)

    assert bool(targets["start_target"].isna().all())


# --- the conditional labels -------------------------------------------------


def test_conditional_labels_are_missing_when_the_player_did_not_appear() -> None:
    """A player who did not appear has no conditional minutes, and zero is not the answer.

    Zero would train the conditional model on a population it is not conditioned over, and
    afterwards nothing could separate "played nil minutes" from "was not in the population".
    """

    targets = build_component_targets(_panel([("2024-25", 1, 1, 0, 0), ("2024-25", 1, 2, 62, 5)]))

    absent = targets.loc[targets["player_id"] == 1]
    present = targets.loc[targets["player_id"] == 2]
    assert bool(absent["minutes_target"].isna().all())
    assert bool(absent["points_target"].isna().all())
    assert present["minutes_target"].tolist() == [62]
    assert present["points_target"].tolist() == [5]


def test_a_negative_score_is_a_real_conditional_label() -> None:
    """Cards and own goals produce genuinely negative points; that is data, not an error."""

    targets = build_component_targets(_panel([("2024-25", 1, 1, 90, -2)]))

    assert targets["points_target"].tolist() == [-2]


def test_a_double_gameweek_keeps_its_total_minutes() -> None:
    """The panel is one row per gameweek, so a two-fixture week carries the sum.

    135 minutes is only possible across two fixtures. Capping it at 90 would make the
    conditional minutes label disagree with the calendar the model is told about.
    """

    targets = build_component_targets(_panel([("2024-25", 26, 1, 135, 11)]))

    assert targets["minutes_target"].tolist() == [135]


# --- shape and safety -------------------------------------------------------


def test_the_contract_declares_its_columns_and_one_version() -> None:
    targets = build_component_targets(_panel([("2024-25", 1, 1, 90, 6)]))

    assert TARGET_CONTRACT_VERSION == "phase_c_component_targets_v1"
    assert tuple(targets.columns) == COMPONENT_TARGET_COLUMNS


def test_the_input_frame_is_not_modified() -> None:
    panel = _panel([("2024-25", 2, 2, 45, 3), ("2024-25", 1, 1, 90, 6)])
    before = panel.copy(deep=True)

    build_component_targets(panel)

    assert_frame_equal(panel, before)


def test_the_result_is_sorted_by_the_canonical_key_whatever_the_input_order() -> None:
    rows = [("2024-25", 2, 1, 45, 3), ("2023-24", 5, 9, 90, 6), ("2024-25", 1, 1, 0, 0)]

    forward = build_component_targets(_panel(rows))
    reversed_input = build_component_targets(_panel(list(reversed(rows))))

    assert_frame_equal(forward, reversed_input)
    assert forward["season"].tolist() == ["2023-24", "2024-25", "2024-25"]


def test_a_repeated_player_gameweek_is_refused() -> None:
    """A gameweek total cannot be read off one row if the key appears twice."""

    with pytest.raises(DuplicateRecordsError):
        build_component_targets(_panel([("2024-25", 1, 1, 90, 6), ("2024-25", 1, 1, 45, 2)]))


def test_a_panel_missing_a_required_column_is_refused() -> None:
    with pytest.raises(FeatureConfigurationError, match="missing required columns"):
        build_component_targets(_panel([("2024-25", 1, 1, 90, 6)]).drop(columns=["minutes"]))

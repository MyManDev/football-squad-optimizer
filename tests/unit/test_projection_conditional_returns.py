"""Tests for projection-conditional return-shape measurement."""

from typing import Any

import pandas as pd
import pytest

from squadopt.experiments.projection_conditional_returns import (
    INCONCLUSIVE,
    NOT_LOCALIZED,
    POSITION_EXPECTED_FULL,
    POSITION_EXPECTED_RECENT,
    POSITION_FULL,
    PROJECTION_AND_RECENCY,
    PROJECTION_CANDIDATE,
    RECENCY_CANDIDATE,
    compare_fold,
    expected_points_band,
    recent_history_fold_ids,
    return_state,
    summarise,
)
from squadopt.experiments.shadow_squad_calibration import SquadShadowError


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0.0, 0), (2.999, 0), (3.0, 1), (4.0, 2), (5.0, 3), (6.0, 4), (20.0, 4)],
)
def test_expected_points_bands_have_frozen_boundaries(value: float, expected: int) -> None:
    assert expected_points_band(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [(-3.0, 0), (1.0, 0), (2.0, 1), (3.0, 1), (4.0, 2), (5.0, 2), (6.0, 3)],
)
def test_return_states_are_exhaustive(value: float, expected: int) -> None:
    assert return_state(value) == expected


def test_invalid_expected_and_non_integral_returns_fail_closed() -> None:
    with pytest.raises(SquadShadowError, match="expected points"):
        expected_points_band(-0.1)
    with pytest.raises(SquadShadowError, match="integers"):
        return_state(2.5)


def _history() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for gameweek in range(1, 13):
        for player in range(1, 21):
            predicted = 5.2 if player <= 10 else 3.5
            realized = float((player + gameweek) % 8)
            rows.append(
                {
                    "fold_id": f"2022-23-gw{gameweek}",
                    "season": "2022-23",
                    "gameweek": gameweek,
                    "player_id": player,
                    "position": "MID" if player <= 15 else "FWD",
                    "predicted_points": predicted,
                    "realized_points": realized,
                    "residual": realized - predicted,
                    "minutes": 90.0,
                }
            )
    return pd.DataFrame(rows)


def _starters() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "fold_id": ["2023-24-gw10", "2023-24-gw10", "2023-24-gw10"],
            "season": ["2023-24"] * 3,
            "player_id": [101, 102, 103],
            "position": ["MID", "FWD", "MID"],
            "expected_points": [5.4, 3.4, 4.2],
            "realized_points": [2.0, 6.0, 1.0],
            "realized_residual": [-3.4, 2.6, -3.2],
            "minutes": [90.0, 90.0, 20.0],
        }
    )


def test_recent_history_uses_numeric_gameweek_order() -> None:
    history = _history()
    ids = tuple(history["fold_id"].drop_duplicates())

    assert recent_history_fold_ids(history, tuple(reversed(ids))) == tuple(
        f"2022-23-gw{gameweek}" for gameweek in range(5, 13)
    )


def test_compare_fold_keeps_targets_aligned_and_inputs_unchanged() -> None:
    history = _history()
    starters = _starters()
    before_history = history.copy(deep=True)
    before_starters = starters.copy(deep=True)

    compared = compare_fold(starters, history, tuple(history["fold_id"].drop_duplicates()))

    assert len(compared) == 6
    assert compared.groupby("arm")["player_id"].apply(list).to_dict() == {
        POSITION_FULL: [101, 102],
        POSITION_EXPECTED_FULL: [101, 102],
        POSITION_EXPECTED_RECENT: [101, 102],
    }
    assert compared["brier"].between(0.0, 2.0).all()
    pd.testing.assert_frame_equal(history, before_history)
    pd.testing.assert_frame_equal(starters, before_starters)


def test_conditional_source_falls_back_deterministically() -> None:
    compared = compare_fold(_starters(), _history(), tuple(_history()["fold_id"].drop_duplicates()))
    sources = compared.loc[compared["arm"].eq(POSITION_EXPECTED_FULL)].set_index("player_id")

    assert sources.loc[101, "source"] == "position_band"
    assert bool(sources.loc[101, "direct_cell"])
    assert sources.loc[102, "source"] == "position_band"
    assert bool(sources.loc[102, "direct_cell"])


def test_target_fold_and_thin_pooled_history_fail_closed() -> None:
    history = _history()
    with pytest.raises(SquadShadowError, match="target fold"):
        compare_fold(
            _starters(),
            history.assign(fold_id="2023-24-gw10"),
            ("2023-24-gw10",),
        )

    thin = history.iloc[:10]
    with pytest.raises(SquadShadowError, match="insufficient support"):
        compare_fold(_starters(), thin, ("2022-23-gw1",))


def test_history_row_order_does_not_change_fold_readings() -> None:
    history = _history()
    ids = tuple(history["fold_id"].drop_duplicates())
    expected = compare_fold(_starters(), history, ids).sort_values(["player_id", "arm"])
    actual = compare_fold(_starters(), history.sample(frac=1.0, random_state=11), ids).sort_values(
        ["player_id", "arm"]
    )

    pd.testing.assert_frame_equal(
        actual.reset_index(drop=True), expected.reset_index(drop=True), check_exact=True
    )


def _summary_for_classification(
    *,
    projection_high: float,
    recent_high: float,
    localization_low: float,
    projection_tail_high: float = 0.0,
    recent_tail_high: float = 0.0,
    coverage: float = 1.0,
) -> dict[str, Any]:
    return {
        "arms": {
            POSITION_EXPECTED_FULL: {"fold_count": 37, "direct_cell_coverage": coverage},
            POSITION_EXPECTED_RECENT: {"fold_count": 37, "direct_cell_coverage": coverage},
        },
        "projection_localization": {
            "paired_fold_count": 37,
            "groups": {
                "low": {"target_rows": 100, "unique_players": 30},
                "high": {"target_rows": 100, "unique_players": 30},
            },
            "high_minus_low_ordinary_gap": {"bootstrap_low": localization_low},
        },
        "projection_comparison": {
            "brier_delta": {"bootstrap_high": projection_high},
            "absolute_q25_gap_delta": {"bootstrap_high": projection_tail_high},
        },
        "recency_comparison": {
            "brier_delta": {"bootstrap_high": recent_high},
            "absolute_q25_gap_delta": {"bootstrap_high": recent_tail_high},
        },
        "recent_vs_position_comparison": {
            "brier_delta": {"bootstrap_high": projection_high + recent_high},
            "absolute_q25_gap_delta": {"bootstrap_high": recent_tail_high},
        },
    }


@pytest.mark.parametrize(
    ("summary", "expected"),
    [
        (
            _summary_for_classification(
                projection_high=-0.01, recent_high=-0.01, localization_low=0.01
            ),
            PROJECTION_AND_RECENCY,
        ),
        (
            _summary_for_classification(
                projection_high=-0.01, recent_high=0.01, localization_low=0.01
            ),
            PROJECTION_CANDIDATE,
        ),
        (
            _summary_for_classification(
                projection_high=0.01, recent_high=-0.02, localization_low=-0.01
            ),
            RECENCY_CANDIDATE,
        ),
        (
            _summary_for_classification(
                projection_high=0.01, recent_high=0.01, localization_low=-0.01
            ),
            NOT_LOCALIZED,
        ),
        (
            _summary_for_classification(
                projection_high=-0.01, recent_high=0.01, localization_low=0.01, coverage=0.79
            ),
            INCONCLUSIVE,
        ),
    ],
)
def test_classification_follows_the_frozen_decision_tree(
    summary: dict[str, Any], expected: str
) -> None:
    from squadopt.experiments.projection_conditional_returns import classify

    assert classify(summary) == expected


def test_summary_is_row_order_invariant() -> None:
    compared = compare_fold(_starters(), _history(), tuple(_history()["fold_id"].drop_duplicates()))
    second = compared.assign(fold_id="2023-24-gw11")
    population = pd.concat([compared, second], ignore_index=True)

    assert summarise(population) == summarise(population.sample(frac=1.0, random_state=7))


def test_recency_cannot_be_selected_while_it_remains_worse_than_position() -> None:
    summary = _summary_for_classification(
        projection_high=0.10,
        recent_high=-0.02,
        localization_low=-0.01,
    )

    from squadopt.experiments.projection_conditional_returns import classify

    assert classify(summary) == NOT_LOCALIZED


def test_empty_localization_population_is_inconclusive() -> None:
    compared = compare_fold(
        _starters().loc[_starters()["expected_points"] < 5.0],
        _history(),
        tuple(_history()["fold_id"].drop_duplicates()),
    )
    population = pd.concat(
        [compared.assign(fold_id=f"2023-24-gw{gameweek}") for gameweek in range(10, 40)],
        ignore_index=True,
    )
    result = summarise(population)

    from squadopt.experiments.projection_conditional_returns import classify

    assert result["projection_localization"]["high_minus_low_ordinary_gap"] is None
    assert classify(result) == INCONCLUSIVE

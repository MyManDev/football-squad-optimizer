"""Tests for direct empirical marginal-shape comparison."""

from typing import Any

import pandas as pd
import pytest

from squadopt.experiments.conditional_marginal_shape import (
    APPEARANCE_CANDIDATE,
    BOTH_ADEQUATE,
    CANONICAL,
    RAW_COMPLETED,
    RAW_UNCONDITIONAL,
    RECOMBINATION_CANDIDATE,
    UNRESOLVED,
    attach_history_minutes,
    classify,
    compare_fold,
    reconcile_completed_canonical,
    summarise,
)
from squadopt.experiments.shadow_squad_calibration import SquadShadowError


def _starter_rows() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "fold_id": ["2023-24-gw10", "2023-24-gw10", "2023-24-gw10"],
            "season": ["2023-24"] * 3,
            "player_id": [1, 2, 3],
            "position": ["MID", "MID", "FWD"],
            "minutes": [90.0, 60.0, 59.0],
            "realized_residual": [-4.0, 1.0, -8.0],
            "downside_threshold": [-2.0, -2.0, -2.0],
            "scenario_downside_rate": [0.25, 0.25, 0.25],
            "realized_downside": [True, False, True],
        }
    )


def _history() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "fold_id": ["prior-1", "prior-2", "prior-3", "prior-4", *(["prior-9"] * 8)],
            "season": ["2022-23"] * 12,
            "gameweek": [1, 2, 3, 4, *([9] * 8)],
            "player_id": [1] * 4 + [10, 11, 12, 13, 14, 15, 16, 17],
            "position": ["MID"] * 10 + ["FWD", "FWD"],
            "residual": [-5.0, -3.0, 1.0, 7.0, -4.0, -2.0, 0.0, 2.0, 4.0, 6.0, -1.0, 3.0],
            "minutes": [90.0, 0.0, 90.0, 90.0, 90.0, 90.0, 90.0, 90.0, 90.0, 90.0, 90.0, 90.0],
        }
    )


def _history_ids() -> tuple[str, ...]:
    return tuple(_history()["fold_id"].drop_duplicates())


def _classification_summary(
    *, canonical: tuple[float, float], raw: tuple[float, float], completed: tuple[float, float]
) -> dict[str, Any]:
    def arm(interval: tuple[float, float]) -> dict[str, Any]:
        return {
            "fold_count": 30,
            "gap": {
                "mean": sum(interval) / 2,
                "bootstrap_low": interval[0],
                "bootstrap_high": interval[1],
            },
        }

    return {
        "arms": {
            CANONICAL: arm(canonical),
            RAW_UNCONDITIONAL: arm(raw),
            RAW_COMPLETED: arm(completed),
        }
    }


def test_attach_history_minutes_is_exact_and_fails_on_missing_rows() -> None:
    residuals = _history().drop(columns="minutes")
    panel = (
        _history()
        .loc[:, ["season", "gameweek", "player_id", "minutes"]]
        .drop_duplicates(["season", "gameweek", "player_id"])
    )

    attached = attach_history_minutes(residuals, panel)
    assert attached["minutes"].tolist() == _history()["minutes"].tolist()

    with pytest.raises(SquadShadowError, match="missing minutes"):
        attach_history_minutes(residuals, panel.loc[panel["player_id"] != 17])


def test_compare_fold_uses_player_then_position_and_excludes_partial_outcome() -> None:
    compared = compare_fold(
        _starter_rows(),
        _history(),
        _history_ids(),
        min_player_observations=4,
    )

    assert len(compared) == 6
    assert set(compared["player_id"]) == {1, 2}
    raw = compared.loc[compared["arm"] == RAW_UNCONDITIONAL].set_index("player_id")
    assert raw.loc[1, "source"] == "player"
    assert raw.loc[2, "source"] == "position"


def test_completed_arm_filters_history_before_choosing_the_source() -> None:
    compared = compare_fold(
        _starter_rows(),
        _history(),
        _history_ids(),
        min_player_observations=4,
    )
    player_one = compared.loc[
        (compared["arm"] == RAW_COMPLETED) & (compared["player_id"] == 1)
    ].iloc[0]

    assert player_one["source"] == "position"


def test_empirical_expected_rate_preserves_strict_ties() -> None:
    history = _history()
    history.loc[:, "residual"] = [-2.0] * 9 + [0.0, 1.0, 2.0]
    compared = compare_fold(
        _starter_rows(),
        history,
        _history_ids(),
        min_player_observations=20,
    )
    raw = compared.loc[compared["arm"] == RAW_UNCONDITIONAL]

    assert (raw["threshold"] == -2.0).all()
    assert (raw["expected_rate"] == 0.0).all()


def test_summary_reports_paired_fold_gaps_and_sources() -> None:
    fold_one = compare_fold(
        _starter_rows(),
        _history(),
        _history_ids(),
        min_player_observations=4,
    )
    fold_two = fold_one.assign(fold_id="2023-24-gw11")

    result = summarise(pd.concat([fold_one, fold_two], ignore_index=True))
    arms = result["arms"]
    assert isinstance(arms, dict)
    assert arms[CANONICAL]["fold_count"] == 2
    assert arms[CANONICAL]["starter_rows"] == 4
    assert arms[RAW_UNCONDITIONAL]["source_counts"] == {"player": 2, "position": 2}


@pytest.mark.parametrize(
    ("raw", "completed", "expected"),
    [
        ((0.01, 0.10), (-0.01, 0.05), APPEARANCE_CANDIDATE),
        ((-0.01, 0.05), (0.01, 0.10), RECOMBINATION_CANDIDATE),
        ((-0.01, 0.05), (-0.02, 0.03), BOTH_ADEQUATE),
        ((0.01, 0.05), (0.02, 0.06), UNRESOLVED),
    ],
)
def test_classification_follows_pre_registered_interval_logic(
    raw: tuple[float, float], completed: tuple[float, float], expected: str
) -> None:
    summary = _classification_summary(canonical=(0.05, 0.20), raw=raw, completed=completed)
    assert classify(summary) == expected


def test_classification_refuses_when_canonical_is_already_compatible() -> None:
    summary = _classification_summary(
        canonical=(-0.01, 0.05),
        raw=(-0.01, 0.05),
        completed=(-0.01, 0.05),
    )
    assert classify(summary) == UNRESOLVED


def test_reconciliation_checks_all_prior_completed_appearance_fields() -> None:
    fold = compare_fold(
        _starter_rows(),
        _history(),
        _history_ids(),
        min_player_observations=4,
    )
    summary = summarise(fold)
    canonical = summary["arms"][CANONICAL]
    prior = {
        "starter_rows": canonical["starter_rows"],
        "realized_downside_rate": canonical["realized_event_rate"],
        "scenario_expected_downside_rate": canonical["source_expected_event_rate"],
    }
    reconcile_completed_canonical(summary, prior)

    prior["realized_downside_rate"] = 0.99
    with pytest.raises(SquadShadowError, match="does not reproduce"):
        reconcile_completed_canonical(summary, prior)

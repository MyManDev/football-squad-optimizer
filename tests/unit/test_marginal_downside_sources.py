"""Focused tests for the pre-registered marginal-downside accounting."""

from typing import Any

import pandas as pd
import pytest

import squadopt.experiments.downside_dependence as dependence
from squadopt.experiments.downside_dependence import DownsideReading
from squadopt.experiments.marginal_downside_sources import (
    APPEARANCE_DOMINANT,
    FULL_APPEARANCE,
    FULL_APPEARANCE_DOMINANT,
    MIXED,
    NO_APPEARANCE,
    PARTIAL_APPEARANCE,
    classify,
    enrich_starters,
    summarise,
)
from squadopt.experiments.shadow_squad_calibration import SquadShadowError


def _starters(*, minutes: list[float] | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    player_ids = list(range(1, 12))
    starters = pd.DataFrame(
        {
            "fold_id": ["2023-24-gw10"] * 11,
            "season": ["2023-24"] * 11,
            "gameweek": [10] * 11,
            "player_id": player_ids,
            "team_id": [f"team-{value % 5}" for value in player_ids],
            "position": ["MID"] * 11,
            "expected_points": [5.0] * 11,
            "realized_points": [2.0] * 11,
            "realized_residual": [-3.0] * 11,
            "downside_threshold": [-1.0] * 11,
            "scenario_downside_rate": [0.25] * 11,
            "realized_downside": [True] * 11,
        }
    )
    panel = pd.DataFrame(
        {
            "season": ["2023-24"] * 11,
            "gameweek": [10] * 11,
            "player_id": player_ids,
            "minutes": minutes if minutes is not None else [90.0] * 11,
        }
    )
    return starters, panel


def _summary(*, folds: int, no_appearance: float, partial: float, full: float) -> dict[str, Any]:
    return {
        "fold_count": folds,
        "minute_buckets": {
            NO_APPEARANCE: {"excess_contribution": no_appearance},
            PARTIAL_APPEARANCE: {"excess_contribution": partial},
            FULL_APPEARANCE: {"excess_contribution": full},
        },
    }


def test_enrich_starters_uses_declared_history_and_keeps_missing_location() -> None:
    starters, panel = _starters()
    residuals = pd.DataFrame(
        {
            "fold_id": ["prior", "prior", "future"],
            "player_id": [1, 1, 1],
            "residual": [-2.0, 4.0, -100.0],
        }
    )

    enriched = enrich_starters(starters, panel, residuals, ("prior",))

    player_one = enriched.loc[enriched["player_id"] == 1].iloc[0]
    player_two = enriched.loc[enriched["player_id"] == 2].iloc[0]
    assert player_one["prior_residual_count"] == 2
    assert player_one["omitted_player_location"] == pytest.approx(1.0)
    assert player_two["prior_residual_count"] == 0
    assert pd.isna(player_two["omitted_player_location"])


def test_minute_bucket_boundaries_are_explicit() -> None:
    minutes = [0.0, 1.0, 59.0, 60.0, 90.0, 120.0, 90.0, 90.0, 90.0, 90.0, 90.0]
    starters, panel = _starters(minutes=minutes)

    enriched = enrich_starters(
        starters,
        panel,
        pd.DataFrame(columns=["fold_id", "player_id", "residual"]),
        (),
    )

    assert enriched["minute_bucket"].tolist()[:6] == [
        NO_APPEARANCE,
        PARTIAL_APPEARANCE,
        PARTIAL_APPEARANCE,
        FULL_APPEARANCE,
        FULL_APPEARANCE,
        FULL_APPEARANCE,
    ]


def test_missing_minutes_fail_closed() -> None:
    starters, panel = _starters()
    panel = panel.loc[panel["player_id"] != 11]

    with pytest.raises(SquadShadowError, match="minutes are missing"):
        enrich_starters(
            starters,
            panel,
            pd.DataFrame(columns=["fold_id", "player_id", "residual"]),
            (),
        )


def test_bucket_contributions_sum_to_total_excess() -> None:
    starters, panel = _starters(
        minutes=[0.0, 15.0, 90.0, 90.0, 90.0, 90.0, 90.0, 90.0, 90.0, 90.0, 90.0]
    )
    enriched = enrich_starters(
        starters,
        panel,
        pd.DataFrame(columns=["fold_id", "player_id", "residual"]),
        (),
    )

    summary = summarise(enriched)
    buckets = summary["minute_buckets"]
    assert isinstance(buckets, dict)
    bucket_total = sum(float(item["excess_contribution"]) for item in buckets.values())
    assert bucket_total == pytest.approx(float(summary["total_downside_excess"]))
    assert sum(int(item["starter_rows"]) for item in buckets.values()) == 11


@pytest.mark.parametrize(
    ("summary", "expected"),
    [
        (_summary(folds=30, no_appearance=4.0, partial=3.0, full=2.0), APPEARANCE_DOMINANT),
        (
            _summary(folds=30, no_appearance=1.0, partial=1.0, full=2.0),
            FULL_APPEARANCE_DOMINANT,
        ),
        (_summary(folds=29, no_appearance=4.0, partial=3.0, full=2.0), MIXED),
        (_summary(folds=30, no_appearance=-1.0, partial=-1.0, full=-2.0), MIXED),
    ],
)
def test_classification_is_the_pre_registered_accounting_rule(
    summary: dict[str, Any], expected: str
) -> None:
    assert classify(summary) == expected


def test_read_fold_wrapper_preserves_the_reading(monkeypatch: pytest.MonkeyPatch) -> None:
    reading = DownsideReading(
        fold_id="fold",
        season="2023-24",
        realized_marginal_rate=0.0,
        expected_marginal_rate=0.0,
        realized_joint_rate=0.0,
        expected_joint_rate=0.0,
        realized_same_team_joint_rate=None,
        expected_same_team_joint_rate=None,
        realized_different_team_joint_rate=0.0,
        expected_different_team_joint_rate=0.0,
        realized_downside_count=0,
        count_mid_pit=0.0,
        count_above_q90=False,
        covariance_contribution=0.0,
        full_score_pit=0.5,
        full_score_below_q10=False,
    )
    monkeypatch.setattr(
        dependence,
        "read_fold_with_starters",
        lambda *args: (reading, pd.DataFrame()),
    )

    assert dependence.read_fold(*([None] * 5)) is reading  # type: ignore[arg-type]

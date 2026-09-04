"""Tests for the fixture-group calibration contract (`projection_uncertainty_v2`).

The v1 contract must be untouched: its configuration fingerprint reproduces the one the
committed control calibration recorded, and a v1 calibration carries no fixture cells.
The v2 contract needs a fixture count on every row, calibrates a wider radius on
doubles, gives a blank a zero interval, and refuses rows without a calendar.
"""

import json
import random
from pathlib import Path

import pandas as pd
import pytest

from squadopt.evaluation import EvaluationFold
from squadopt.uncertainty import (
    PROJECTION_UNCERTAINTY_FIXTURE_CONTRACT_VERSION,
    UncertaintyConfig,
    UncertaintyConfigurationError,
    UncertaintyValidationError,
    apply_projection_uncertainty,
    attach_fixture_counts_to_folds,
    evaluate_projection_uncertainty,
    fit_projection_uncertainty,
)

POSITIONS = ("GK", "DEF", "MID", "FWD")
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _fold(season: str, gameweek: int, generator: random.Random, *, doubles: bool) -> EvaluationFold:
    """Twelve players per position; the first four double when ``doubles`` (twice the
    residual spread), the fifth is blank (zero projection, zero points)."""

    rows: list[dict[str, object]] = []
    realized: list[dict[str, object]] = []
    player = 100
    for position in POSITIONS:
        for index in range(12):
            player += 1
            if index == 4:
                count = 0
            elif doubles and index < 4:
                count = 2
            else:
                count = 1
            expected = 0.0 if count == 0 else 3.0 * count
            spread = 0.0 if count == 0 else (2.0 if count == 2 else 1.0)
            rows.append(
                {
                    "player_id": player,
                    "name": f"P{player}",
                    "team_id": f"Club {index}",
                    "position": position,
                    "price_tenths": 50,
                    "expected_points": expected,
                    "fixture_count": count,
                }
            )
            realized.append(
                {"player_id": player, "total_points": expected + generator.gauss(0.0, spread)}
            )
    return EvaluationFold(
        fold_id=f"{season}-gw{gameweek:02d}",
        projections=pd.DataFrame(rows),
        realized_points=pd.DataFrame(realized),
        metadata={"season": season, "gameweek": gameweek},
    )


def _folds(season: str, generator: random.Random) -> tuple[EvaluationFold, ...]:
    return tuple(_fold(season, gw, generator, doubles=gw % 3 == 0) for gw in range(2, 30))


V2 = UncertaintyConfig(
    development_seasons=("2021-22",),
    holdout_season="2022-23",
    grouping="position_fixture_group",
    contract_version=PROJECTION_UNCERTAINTY_FIXTURE_CONTRACT_VERSION,
)


def test_the_v1_configuration_fingerprint_still_reproduces_the_committed_record() -> None:
    document = json.loads(
        (REPOSITORY_ROOT / "docs" / "control_uncertainty_calibration.json").read_text(
            encoding="utf-8"
        )
    )
    config = UncertaintyConfig(
        confidence_level=float(document["confidence_level"]),
        development_seasons=tuple(document["calibration_seasons"]),
        holdout_season=str(document["evaluation_season"]),
    )
    assert config.grouping == "position"
    assert (
        config.configuration_fingerprint == document["position_level"]["configuration_fingerprint"]
    )


def test_grouping_and_contract_version_must_agree() -> None:
    with pytest.raises(UncertaintyConfigurationError, match="contract_version"):
        UncertaintyConfig(grouping="position_fixture_group")
    with pytest.raises(UncertaintyConfigurationError, match="contract_version"):
        UncertaintyConfig(contract_version=PROJECTION_UNCERTAINTY_FIXTURE_CONTRACT_VERSION)
    with pytest.raises(UncertaintyConfigurationError, match="grouping"):
        UncertaintyConfig(grouping="team")
    assert V2.uses_fixture_groups and not UncertaintyConfig().uses_fixture_groups
    assert (
        V2.configuration_fingerprint
        != UncertaintyConfig(
            development_seasons=("2021-22",), holdout_season="2022-23"
        ).configuration_fingerprint
    )


def test_the_fixture_contract_calibrates_doubles_wider_and_covers_them() -> None:
    generator = random.Random(3)
    development = _folds("2021-22", generator)
    holdout = _folds("2022-23", generator)

    v1 = fit_projection_uncertainty(
        development, UncertaintyConfig(development_seasons=("2021-22",), holdout_season="2022-23")
    )
    v2 = fit_projection_uncertainty(development, V2)

    assert v1.fixture_groups == {}
    assert set(v2.fixture_groups) == {
        f"{p}/{g}" for p in POSITIONS for g in ("single", "double_plus")
    }
    for position in POSITIONS:
        single = v2.fixture_groups[f"{position}/single"]
        double = v2.fixture_groups[f"{position}/double_plus"]
        assert double.interval_radius > single.interval_radius
        assert single.source == "position_fixture_group"
        assert double.fixture_group == "double_plus" and double.position == position
    # Blanks are not calibrated on: the pool excludes them.
    assert v2.pooled_observations < v1.pooled_observations
    assert v2.diagnostics["blank_rows_excluded_from_calibration"] is True

    scored_v1 = evaluate_projection_uncertainty(holdout, v1)
    scored_v2 = evaluate_projection_uncertainty(holdout, v2)
    metrics = scored_v2.diagnostics["fixture_group_metrics"]
    assert isinstance(metrics, dict)
    assert abs(metrics["double_plus"]["empirical_coverage"] - 0.90) < 0.06
    assert metrics["blank"]["empirical_coverage"] == 1.0
    assert metrics["blank"]["mean_interval_width"] == 0.0
    assert "fixture_group_metrics" not in scored_v1.diagnostics


def test_applying_the_fixture_contract_needs_a_calendar_and_zeroes_a_blank() -> None:
    generator = random.Random(5)
    development = _folds("2021-22", generator)
    v2 = fit_projection_uncertainty(development, V2)
    table = development[0].projections

    calibrated = apply_projection_uncertainty(table, v2)
    blank = calibrated.table.loc[calibrated.table["fixture_count"] == 0]
    assert (blank["prediction_interval_lower"] == 0.0).all()
    assert (blank["prediction_interval_upper"] == 0.0).all()
    assert (blank["uncertainty_source"] == "blank_zero").all()
    doubles = calibrated.table.loc[calibrated.table["fixture_count"] == 2]
    assert doubles["uncertainty_group"].str.endswith("/double_plus").all()

    with pytest.raises(UncertaintyValidationError, match="fixture_count"):
        apply_projection_uncertainty(table.drop(columns="fixture_count"), v2)
    with pytest.raises(UncertaintyValidationError, match="fixture_count"):
        fit_projection_uncertainty(
            tuple(
                EvaluationFold(
                    fold_id=fold.fold_id,
                    projections=fold.projections.drop(columns="fixture_count"),
                    realized_points=fold.realized_points,
                    metadata=dict(fold.metadata),
                )
                for fold in development
            ),
            V2,
        )


def test_the_calendar_is_attached_to_folds_by_season_gameweek_and_club() -> None:
    generator = random.Random(9)
    bare = tuple(
        EvaluationFold(
            fold_id=fold.fold_id,
            projections=fold.projections.drop(columns="fixture_count"),
            realized_points=fold.realized_points,
            metadata=dict(fold.metadata),
        )
        for fold in _folds("2021-22", generator)[:3]
    )
    calendar = pd.DataFrame(
        [
            {
                "season": "2021-22",
                "gameweek": gw,
                "team_id": f"Club {index}",
                "fixture_count": 2 if index == 0 and gw == 3 else 1,
            }
            for gw in (2, 3, 4)
            for index in range(12)
            if index != 4  # Club 4 is absent from the calendar: a blank
        ]
    )

    attached = attach_fixture_counts_to_folds(bare, calendar)

    assert [fold.fold_id for fold in attached] == [fold.fold_id for fold in bare]
    second = attached[1].projections
    assert (second.loc[second["team_id"] == "Club 0", "fixture_count"] == 2).all()
    assert (second.loc[second["team_id"] == "Club 4", "fixture_count"] == 0).all()
    assert (second.loc[second["team_id"] == "Club 1", "fixture_count"] == 1).all()
    with pytest.raises(UncertaintyValidationError, match="missing columns"):
        attach_fixture_counts_to_folds(bare, calendar.drop(columns="team_id"))

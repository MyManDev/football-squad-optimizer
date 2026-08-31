"""Tests for exact selected-XI score-component attribution."""

from typing import Any

import pandas as pd
import pytest

from squadopt.experiments.component_attribution import (
    COMPONENT_NOT_LOCALIZED,
    COMPONENTS,
    CONTROL,
    INCONCLUSIVE,
    SHARED_COMPONENT_FAILURE,
    aggregate_player_gameweeks,
    attribute_fold,
    classify,
    score_fixture_components,
    summarise,
)
from squadopt.experiments.shadow_squad_calibration import SquadShadowError


def _fixture_rows() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "season": ["2023-24", "2023-24", "2023-24", "2023-24"],
            "gameweek": [10, 10, 10, 10],
            "fold_id": ["2023-24-gw10"] * 4,
            "fixture_id": [100, 101, 100, 100],
            "player_id": [1, 1, 2, 3],
            "position": ["GK", "GK", "MID", "FWD"],
            "minutes": [61, 61, 90, 45],
            "total_points": [12, 0, 10, 0],
            "goals_scored": [0, 0, 1, 0],
            "assists": [0, 0, 0, 0],
            "clean_sheets": [1, 0, 0, 0],
            "goals_conceded": [0, 4, 0, 0],
            "saves": [9, 0, 0, 0],
            "bonus": [3, 0, 3, 0],
            "yellow_cards": [0, 0, 0, 1],
            "red_cards": [0, 0, 0, 0],
            "own_goals": [0, 0, 0, 0],
            "penalties_missed": [0, 0, 0, 0],
            "penalties_saved": [0, 0, 0, 0],
        }
    )


def test_fixture_components_reconstruct_fpl_points_without_mutation() -> None:
    fixture_rows = _fixture_rows()
    before = fixture_rows.copy(deep=True)

    scored = score_fixture_components(fixture_rows)

    assert scored.loc[:, list(COMPONENTS)].sum(axis=1).tolist() == [12, 0, 10, 0]
    assert scored.loc[0, list(COMPONENTS)].tolist() == [2, 0, 7, 3, 0]
    assert scored.loc[1, list(COMPONENTS)].tolist() == [2, 0, -2, 0, 0]
    assert scored.loc[2, list(COMPONENTS)].tolist() == [2, 5, 0, 3, 0]
    assert scored.loc[3, list(COMPONENTS)].tolist() == [1, 0, 0, 0, -1]
    pd.testing.assert_frame_equal(fixture_rows, before)


def test_double_gameweek_appearance_is_scored_before_aggregation() -> None:
    scored = score_fixture_components(_fixture_rows())

    aggregated = aggregate_player_gameweeks(scored)
    goalkeeper = aggregated.loc[aggregated["player_id"].eq(1)].iloc[0]

    assert goalkeeper["minutes"] == 122
    assert goalkeeper["appearance"] == 4
    assert goalkeeper["total_points"] == 12
    assert goalkeeper["fixture_count"] == 2


def test_invalid_fixture_identity_and_mismatched_points_fail_closed() -> None:
    rows = _fixture_rows()
    with pytest.raises(SquadShadowError, match="reconstruct"):
        score_fixture_components(rows.assign(total_points=[11, 0, 10, 0]))

    scored = score_fixture_components(rows)
    duplicated = pd.concat([scored, scored.iloc[[0]]], ignore_index=True)
    with pytest.raises(SquadShadowError, match="repeat"):
        aggregate_player_gameweeks(duplicated)


def test_component_loader_refuses_holdout_before_reading() -> None:
    from pathlib import Path

    from scripts.run_component_attribution import load_component_outcomes

    with pytest.raises(SquadShadowError, match="locked confirmation holdout"):
        load_component_outcomes(Path("does-not-exist"), ("2025-26",))


def test_component_loader_uses_stable_roster_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pathlib import Path

    import scripts.run_component_attribution as runner

    raw = (
        _fixture_rows()
        .iloc[[2]]
        .rename(columns={"gameweek": "round", "fixture_id": "fixture", "player_id": "element"})
    )
    raw = raw.drop(columns=["season", "fold_id"])
    roster = pd.DataFrame({"id": [2], "code": [9002]}).astype(str)
    monkeypatch.setattr(Path, "is_file", lambda _path: True)
    monkeypatch.setattr(
        runner,
        "load_csv",
        lambda path: (
            roster.copy(deep=True)
            if Path(path).name == "players_raw.csv"
            else raw.astype(str).copy(deep=True)
        ),
    )

    loaded = runner.load_component_outcomes(Path("archive"), ("2023-24",))

    assert loaded.loc[0, "player_id"] == 9002
    assert loaded.loc[0, "fold_id"] == "2023-24-gw10"
    assert loaded.loc[0, "total_points"] == 10


def _starters() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "fold_id": ["2023-24-gw10"] * 11,
            "season": ["2023-24"] * 11,
            "player_id": list(range(1, 12)),
            "position": [
                "GK",
                "DEF",
                "DEF",
                "DEF",
                "MID",
                "MID",
                "MID",
                "MID",
                "FWD",
                "FWD",
                "FWD",
            ],
            "expected_points": [4.0] * 11,
            "weight": [2.0, *([1.0] * 10)],
        }
    )


def _components(fold_id: str, *, history_offset: int = 0) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    positions = _starters()["position"].tolist()
    for player_id, position in zip(range(1, 12), positions, strict=True):
        appearance = 2 + (1 if history_offset == 0 and player_id == 1 else 0)
        attacking = 1 if player_id % 3 == 0 else 0
        defensive = 1 if position in {"GK", "DEF"} else 0
        bonus = 1 if player_id == 2 else 0
        negative = -1 if player_id == 3 else 0
        rows.append(
            {
                "fold_id": fold_id,
                "season": fold_id[:7],
                "player_id": player_id,
                "position": position,
                "minutes": 90,
                "total_points": appearance + attacking + defensive + bonus + negative,
                "appearance": appearance,
                "attacking": attacking,
                "defensive": defensive,
                "bonus": bonus,
                "negative": negative,
            }
        )
    return pd.DataFrame(rows)


def _history() -> tuple[pd.DataFrame, tuple[str, ...]]:
    fold_ids = tuple(f"2022-23-gw{gameweek:02d}" for gameweek in range(1, 10))
    return (
        pd.concat(
            [_components(fold_id, history_offset=1) for fold_id in fold_ids], ignore_index=True
        ),
        fold_ids,
    )


def test_fold_attribution_closes_identity_and_changes_only_realized_reading() -> None:
    history, fold_ids = _history()
    scores = [40.0, 42.0, 44.0, 46.0, 48.0]

    readings, diagnostics = attribute_fold(
        _starters(),
        _components("2023-24-gw10"),
        history,
        fold_ids,
        scores,
        shift_points=-2.0,
        lower_quantile=0.1,
    )

    assert readings["scenario_mean_score"].nunique() == 1
    assert readings["lower_quantile_score"].nunique() == 1
    assert readings["arm"].tolist() == [CONTROL, *COMPONENTS]
    assert diagnostics["component_score_error"] == pytest.approx(0.0, abs=1e-12)
    assert diagnostics["identity_error"] == pytest.approx(0.0, abs=1e-12)
    assert diagnostics["component_surprises"]["appearance"] == pytest.approx(2.0)
    assert diagnostics["source_counts"] == {"player_position": 11}


def test_captain_weight_is_required_and_target_never_enters_history() -> None:
    history, fold_ids = _history()
    with pytest.raises(SquadShadowError, match="one captain"):
        attribute_fold(
            _starters().assign(weight=1.0),
            _components("2023-24-gw10"),
            history,
            fold_ids,
            [40.0, 41.0],
            shift_points=0.0,
            lower_quantile=0.1,
        )

    future = pd.concat([history, _components("2024-25-gw01")], ignore_index=True)
    with pytest.raises(SquadShadowError, match="future fold"):
        attribute_fold(
            _starters(),
            _components("2023-24-gw10"),
            future,
            (*fold_ids, "2024-25-gw01"),
            [40.0, 41.0],
            shift_points=0.0,
            lower_quantile=0.1,
        )

    with pytest.raises(SquadShadowError, match="starter fold and season"):
        attribute_fold(
            _starters(),
            _components("2023-24-gw11"),
            history,
            fold_ids,
            [40.0, 41.0],
            shift_points=0.0,
            lower_quantile=0.1,
        )

    leaked = pd.concat([history, _components("2023-24-gw10")], ignore_index=True)
    with pytest.raises(SquadShadowError, match="target fold"):
        attribute_fold(
            _starters(),
            _components("2023-24-gw10"),
            leaked,
            (*fold_ids, "2023-24-gw10"),
            [40.0, 41.0],
            shift_points=0.0,
            lower_quantile=0.1,
        )


def test_history_order_does_not_change_attribution() -> None:
    history, fold_ids = _history()
    expected = attribute_fold(
        _starters(),
        _components("2023-24-gw10"),
        history,
        fold_ids,
        [40.0, 45.0],
        shift_points=-2.0,
        lower_quantile=0.1,
    )
    actual = attribute_fold(
        _starters().sample(frac=1.0, random_state=4),
        _components("2023-24-gw10").sample(frac=1.0, random_state=5),
        history.sample(frac=1.0, random_state=6),
        tuple(reversed(fold_ids)),
        [40.0, 45.0],
        shift_points=-2.0,
        lower_quantile=0.1,
    )

    pd.testing.assert_frame_equal(expected[0], actual[0])
    assert expected[1] == actual[1]


def test_summary_bootstraps_fold_level_contrasts_and_counts_sources() -> None:
    readings: list[dict[str, object]] = []
    diagnostics: list[dict[str, object]] = []
    for index in range(37):
        fold_id = f"2023-24-gw{index + 1:02d}"
        control_tail = index < 8
        for arm in (CONTROL, *COMPONENTS):
            normalized_tail = control_tail if arm != "appearance" else index < 4
            readings.append(
                {
                    "fold_id": fold_id,
                    "season": "2023-24",
                    "arm": arm,
                    "realized_score": 50.0,
                    "scenario_mean_score": 50.0,
                    "probability_integral_transform": 0.5,
                    "below_lower_quantile": normalized_tail,
                }
            )
        diagnostics.append(
            {
                "fold_id": fold_id,
                "source_counts": {"player_position": 11},
                "player_source_coverage": 1.0,
                "identity_error": 0.0,
                "component_score_error": 0.0,
                "weighted_minutes": 1080.0,
                "zero_minute_starters": 0,
                "partial_appearance_starters": 0,
                "completed_appearance_starters": 11,
                **{
                    f"surprise_{component}": (
                        -2.0 if component == "appearance" and control_tail else 0.0
                    )
                    for component in COMPONENTS
                },
            }
        )

    result = summarise(pd.DataFrame(readings), pd.DataFrame(diagnostics))

    appearance = result["components"]["appearance"]
    assert appearance["tail_minus_other_surprise"]["bootstrap_high"] < 0.0
    assert appearance["q10_failure_reduction"]["bootstrap_low"] > 0.0
    assert result["source_counts"] == {"player_position": 407, "position": 0, "pooled": 0}
    assert result["maximum_absolute_identity_error"] == 0.0


def _summary(*, localized: tuple[str, ...] = (), folds: int = 37) -> dict[str, Any]:
    arms: dict[str, dict[str, object]] = {
        CONTROL: {
            "fold_count": folds,
            "mean_probability_integral_transform": 0.49,
            "below_lower_quantile_rate": 0.21,
        }
    }
    components: dict[str, dict[str, object]] = {}
    for component in COMPONENTS:
        passes = component in localized
        arms[component] = {
            "fold_count": folds,
            "mean_probability_integral_transform": 0.50 if passes else 0.70,
            "below_lower_quantile_rate": 0.10 if passes else 0.20,
        }
        components[component] = {
            "tail_minus_other_surprise": {
                "mean": -1.0 if passes else 0.0,
                "bootstrap_low": -2.0,
                "bootstrap_high": -0.1 if passes else 0.1,
            },
            "q10_failure_reduction": {
                "mean": 0.1 if passes else 0.0,
                "bootstrap_low": 0.01 if passes else -0.01,
                "bootstrap_high": 0.2,
            },
        }
    return {
        "arms": arms,
        "components": components,
        "maximum_absolute_identity_error": 0.0,
        "maximum_absolute_component_score_error": 0.0,
    }


@pytest.mark.parametrize(
    ("validation", "sensitivity", "expected"),
    [
        (
            _summary(localized=("appearance",)),
            _summary(localized=("appearance",)),
            "appearance_component_localized",
        ),
        (
            _summary(localized=("appearance", "attacking")),
            _summary(localized=("appearance", "attacking")),
            SHARED_COMPONENT_FAILURE,
        ),
        (_summary(), _summary(), COMPONENT_NOT_LOCALIZED),
        (
            _summary(localized=("appearance",), folds=29),
            _summary(localized=("appearance",)),
            INCONCLUSIVE,
        ),
    ],
)
def test_classification_uses_only_frozen_gates(
    validation: dict[str, Any], sensitivity: dict[str, Any], expected: str
) -> None:
    assert classify(validation, sensitivity) == expected


def test_classification_refuses_broken_sensitivity_identity() -> None:
    validation = _summary(localized=("appearance",))
    sensitivity = _summary(localized=("appearance",))
    sensitivity["maximum_absolute_identity_error"] = 0.1

    assert classify(validation, sensitivity) == INCONCLUSIVE


def test_population_reconciliation_fails_closed() -> None:
    from scripts.run_component_attribution import reconcile_population

    seasons = ("2021-22", "2022-23", "2023-24", "2024-25")
    readings = pd.DataFrame(
        {
            "fold_id": [f"{season}-gw01" for season in seasons],
            "season": list(seasons),
            "arm": [CONTROL] * 4,
        }
    )
    diagnostics = pd.DataFrame({"starter_count": [11] * 4})
    recorded: dict[str, object] = {
        "folds_by_season": {season: 1 for season in seasons},
        "total_folds": 4,
        "starter_rows": 44,
    }
    reconcile_population(readings, diagnostics, recorded)

    with pytest.raises(SquadShadowError, match="starter population"):
        reconcile_population(readings, diagnostics, {**recorded, "starter_rows": 45})

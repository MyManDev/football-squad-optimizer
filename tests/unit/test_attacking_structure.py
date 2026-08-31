"""Tests for the pre-registered attacking-blank structure diagnostic."""

from typing import Any

import pandas as pd
import pytest

from squadopt.experiments.attacking_structure import (
    COMMON_WEEK_REFERENCE_EXCESS,
    INCONCLUSIVE,
    MARGINAL_BLANK_EXCESS,
    NOT_LOCALIZED,
    SAME_TEAM_REFERENCE_EXCESS,
    SHARED_REFERENCE_EXCESS,
    WRONG_DIRECTION,
    build_fold_metrics,
    classify,
    summarise,
)
from squadopt.experiments.shadow_squad_calibration import SquadShadowError


def _rows() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "fold_id": ["2023-24-gw10"] * 4,
            "season": ["2023-24"] * 4,
            "player_id": [1, 2, 3, 4],
            "team_id": [10, 10, 20, 30],
            "completed_appearance": [1, 1, 1, 0],
            "attacking_blank": [1, 0, 1, 0],
            "blank_probability": [0.5, 0.25, 0.5, 0.75],
        }
    )


def test_fold_metrics_match_the_declared_arithmetic() -> None:
    metric = build_fold_metrics(_rows())

    assert metric["selected_players"] == 4
    assert metric["eligible_players"] == 3
    assert metric["blank_count"] == 2
    assert metric["same_team_pairs"] == 1
    assert metric["different_team_pairs"] == 2
    assert metric["G"] == pytest.approx(0.25)
    assert metric["O"] == pytest.approx(-0.125)
    assert metric["U"] == pytest.approx(0.0625)
    assert metric["K"] == pytest.approx(-0.1875)


def test_non_completed_rows_are_excluded_and_cannot_be_blanks() -> None:
    rows = _rows()
    rows.loc[3, "blank_probability"] = float("nan")
    metric = build_fold_metrics(rows)
    assert metric["eligible_players"] == 3

    invalid = rows.copy(deep=True)
    invalid.loc[3, "attacking_blank"] = 1
    with pytest.raises(SquadShadowError, match="non-completed"):
        build_fold_metrics(invalid)


@pytest.mark.parametrize(
    "mutation, message",
    [
        (lambda rows: pd.concat([rows, rows.iloc[[0]]], ignore_index=True), "repeats"),
        (lambda rows: rows.assign(blank_probability=1.1), "lie in"),
        (lambda rows: rows.assign(completed_appearance=2), "zero or one"),
    ],
)
def test_invalid_player_rows_fail_closed(mutation: Any, message: str) -> None:
    with pytest.raises(SquadShadowError, match=message):
        build_fold_metrics(mutation(_rows()))


def test_missing_pair_type_is_missing_not_zero() -> None:
    rows = _rows().loc[lambda frame: frame["player_id"].isin([1, 2])]
    metric = build_fold_metrics(rows)

    assert pd.isna(metric["U"])
    assert pd.isna(metric["K"])


def test_summary_bootstraps_folds_and_records_support() -> None:
    base = build_fold_metrics(_rows())
    frames = []
    for gameweek in range(1, 31):
        frames.append({**base, "fold_id": f"2023-24-gw{gameweek:02d}", "season": "2023-24"})
    summary = summarise(pd.DataFrame(frames))

    assert summary["metrics"]["G"] == {
        "mean": pytest.approx(0.25),
        "bootstrap_low": pytest.approx(0.25),
        "bootstrap_high": pytest.approx(0.25),
    }
    assert summary["support"]["metric_folds"] == {"G": 30, "O": 30, "U": 30, "K": 30}
    assert summary["support"]["eligible_players"] == 90
    assert summary["support"]["blank_observations"] == 60
    assert summary["support"]["non_blank_observations"] == 30


def _summary(
    *,
    g: tuple[float, float, float] = (0.0, -0.02, 0.02),
    o: tuple[float, float, float] = (0.0, -0.1, 0.1),
    u: tuple[float, float, float] = (0.0, -0.1, 0.1),
    k: tuple[float, float, float] = (0.0, -0.1, 0.1),
    folds: int = 37,
) -> dict[str, object]:
    def reading(values: tuple[float, float, float]) -> dict[str, float]:
        mean, low, high = values
        return {"mean": mean, "bootstrap_low": low, "bootstrap_high": high}

    return {
        "metrics": {"G": reading(g), "O": reading(o), "U": reading(u), "K": reading(k)},
        "support": {
            "folds": folds,
            "metric_folds": {metric: folds for metric in ("G", "O", "U", "K")},
            "eligible_players": 300,
            "blank_observations": 200,
            "non_blank_observations": 100,
            "same_team_pairs": 100,
            "different_team_pairs": 500,
        },
    }


@pytest.mark.parametrize(
    ("validation", "sensitivity", "expected"),
    [
        (
            _summary(g=(0.08, 0.06, 0.10)),
            _summary(g=(0.01, -0.01, 0.03)),
            MARGINAL_BLANK_EXCESS,
        ),
        (
            _summary(g=(-0.08, -0.10, -0.06)),
            _summary(g=(-0.01, -0.03, 0.01)),
            WRONG_DIRECTION,
        ),
        (
            _summary(o=(1.0, 0.1, 2.0), u=(0.1, 0.01, 0.2)),
            _summary(o=(0.1, -0.1, 0.3), u=(0.01, -0.1, 0.2)),
            COMMON_WEEK_REFERENCE_EXCESS,
        ),
        (
            _summary(k=(0.1, 0.01, 0.2)),
            _summary(k=(0.01, -0.1, 0.2)),
            SAME_TEAM_REFERENCE_EXCESS,
        ),
        (
            _summary(o=(1.0, 0.1, 2.0), u=(0.1, 0.01, 0.2), k=(0.1, 0.01, 0.2)),
            _summary(o=(0.1, -0.1, 0.3), u=(0.01, -0.1, 0.2), k=(0.01, -0.1, 0.2)),
            SHARED_REFERENCE_EXCESS,
        ),
        (_summary(), _summary(), NOT_LOCALIZED),
        (_summary(g=(0.04, -0.02, 0.06)), _summary(), INCONCLUSIVE),
        (_summary(folds=29), _summary(), INCONCLUSIVE),
    ],
)
def test_frozen_classification_tree(
    validation: dict[str, object], sensitivity: dict[str, object], expected: str
) -> None:
    assert classify(validation, sensitivity) == expected


def test_sensitivity_reversal_vetoes_structural_classification() -> None:
    validation = _summary(o=(1.0, 0.1, 2.0), u=(0.1, 0.01, 0.2), k=(0.1, 0.01, 0.2))
    sensitivity = _summary(o=(-0.1, -0.2, 0.0), u=(0.1, 0.0, 0.2), k=(0.1, 0.0, 0.2))

    assert classify(validation, sensitivity) == SAME_TEAM_REFERENCE_EXCESS


def test_runner_builds_blank_rows_from_the_same_fold_decision() -> None:
    from scripts.run_attacking_structure import _attacking_player_rows

    positions = ["GK", "DEF", "DEF", "DEF", "MID", "MID", "MID", "MID", "FWD", "FWD", "FWD"]
    starters = pd.DataFrame(
        {
            "fold_id": ["2023-24-gw10"] * 11,
            "season": ["2023-24"] * 11,
            "player_id": list(range(1, 12)),
            "team_id": [1, 1, 2, 3, 4, 4, 5, 6, 7, 8, 9],
            "position": positions,
            "weight": [2.0, *([1.0] * 10)],
        }
    )
    history_frames: list[pd.DataFrame] = []
    history_ids: list[str] = []
    for gameweek in range(1, 9):
        fold_id = f"2022-23-gw{gameweek:02d}"
        history_ids.append(fold_id)
        history_frames.append(
            pd.DataFrame(
                {
                    "fold_id": [fold_id] * 11,
                    "season": ["2022-23"] * 11,
                    "player_id": list(range(1, 12)),
                    "position": positions,
                    "minutes": [90] * 11,
                    "fixture_count": [1] * 11,
                    "attacking": [gameweek % 2] * 11,
                }
            )
        )
    history = pd.concat(history_frames, ignore_index=True)
    target = pd.DataFrame(
        {
            "fold_id": ["2023-24-gw10"] * 11,
            "season": ["2023-24"] * 11,
            "player_id": list(range(1, 12)),
            "position": positions,
            "minutes": [45, *([90] * 10)],
            "fixture_count": [1] * 10 + [2],
            "attacking": [0] * 11,
        }
    )

    rows, diagnostics = _attacking_player_rows(
        starters,
        target,
        history,
        history_ids,
        {"component_surprises": {"attacking": -6.0}},
    )

    assert len(rows) == 11
    assert rows["player_id"].is_unique
    assert rows["is_captain"].sum() == 1
    assert rows["completed_appearance"].sum() == 10
    assert rows["attacking_blank"].sum() == 10
    assert rows.loc[rows["completed_appearance"].eq(1), "blank_probability"].eq(0.5).all()
    assert rows.loc[rows["completed_appearance"].eq(0), "blank_probability"].isna().all()
    assert diagnostics["weighted_attacking_surprise"] == pytest.approx(-6.0)
    assert diagnostics["history_source_counts"] == {
        "player_position": 10,
        "position": 0,
        "pooled": 0,
        "ineligible": 1,
    }
    assert diagnostics["history_pool_fixture_counts"] == {"1": 80}

    with pytest.raises(SquadShadowError, match="target or future"):
        _attacking_player_rows(
            starters,
            target,
            history,
            ["2024-25-gw01"],
            {"component_surprises": {"attacking": -6.0}},
        )


def test_runner_refuses_an_unregistered_phase2h_artifact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pathlib import Path

    import scripts.run_attacking_structure as runner

    monkeypatch.setattr(runner, "PHASE2H_ARTIFACT", Path("pyproject.toml"))

    with pytest.raises(SquadShadowError, match="pre-registered source"):
        runner._phase2h_document()

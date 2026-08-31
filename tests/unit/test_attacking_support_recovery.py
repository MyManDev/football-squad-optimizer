from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from squadopt.experiments.attacking_hurdle import decompose_player_rows
from squadopt.experiments.attacking_support_recovery import (
    INCONCLUSIVE,
    POSITIVE_SEVERITY_SIGNAL,
    RETURN_REFERENCE_SIGNAL,
    SHARED_REFERENCE_SEVERITY_SIGNAL,
    SUPPORT_RECOVERED_NOT_LOCALIZED,
    AttackingHurdleError,
    build_fold_reading,
    classify,
    recover_player_rows,
    summarise,
)
from squadopt.experiments.shadow_calibration import bootstrap_interval


def _players() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for index in range(11):
        rows.append(
            {
                "fold_id": "2023-24-gw10",
                "season": "2023-24",
                "player_id": index + 1,
                "weight": 2.0 if index == 0 else 1.0,
                "attacking_points": 6.0 if index == 0 else (2.0 if index % 2 else 0.0),
                "history_count": 10,
                "history_attacking_mean": 1.2,
                "history_positive_returns": 6,
                "positive_mean": 2.0,
                "severity_reference_positive_returns": 6,
                "severity_source": "own_positive_returns",
                "recovery_background_mean": float("nan"),
                "recovery_background_positive_returns": 0,
                "recovery_background_source": "",
                "occurrence": 999.0,
                "minutes": 90,
                "fixture_count": 1,
            }
        )
    return pd.DataFrame(rows)


def _phase2j_rows(rows: pd.DataFrame) -> pd.DataFrame:
    source = rows.copy(deep=True)
    source["occurrence_probability"] = source["history_positive_returns"] / source["history_count"]
    return source.drop(
        columns=[
            "recovery_background_mean",
            "recovery_background_positive_returns",
            "recovery_background_source",
        ]
    )


def _recovered_players() -> pd.DataFrame:
    return recover_player_rows(_players())


def _folds(*, season: str = "2023-24", count: int = 30) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for index in range(count):
        tail = index < 10
        rows.append(
            {
                "fold_id": f"{season}-gw{index + 1}",
                "season": season,
                "eligible": True,
                "identity_error": 0.0,
                "positive_target_returns": 5,
                "zero_target_returns": 6,
                "control_below_q10": tail,
                "reference_surprise": -4.0 if tail else 0.0,
                "severity_surprise": -3.0 if tail else 0.0,
                "reference_reduction": 1 if tail else 0,
                "severity_reduction": 1 if tail else 0,
            }
        )
    return pd.DataFrame(rows)


def _classification_summary(
    *, reference: bool, severity: bool, supported: bool = True, reverse: bool = False
) -> dict[str, object]:
    def part(passes: bool) -> dict[str, object]:
        return {
            "tail_minus_other_surprise": {
                "mean": 1.0 if reverse and passes else (-1.0 if passes else 0.0),
                "bootstrap_low": -2.0 if passes else -1.0,
                "bootstrap_high": -0.1 if passes else 1.0,
            },
            "q10_failure_reduction": {
                "mean": -1.0 if reverse and passes else (0.2 if passes else 0.0),
                "bootstrap_low": 0.1 if passes else -0.1,
                "bootstrap_high": 0.3,
            },
        }

    folds = 30 if supported else 29
    return {
        "parts": {"reference": part(reference), "severity": part(severity)},
        "support": {
            "folds": folds,
            "eligible_folds": folds,
            "tail_folds": 10,
            "non_tail_folds": folds - 10,
            "positive_target_returns": 100,
            "zero_target_returns": 100,
        },
        "maximum_absolute_identity_error": 0.0,
    }


def test_zero_and_five_plus_rows_are_exact_phase2j_replay_and_input_is_unchanged() -> None:
    rows = _players()
    rows.loc[0, ["history_attacking_mean", "history_positive_returns"]] = [0.0, 0]
    rows.loc[0, ["positive_mean", "severity_reference_positive_returns"]] = [4.0, 7]
    rows.loc[0, "severity_source"] = "pooled_zero_positive_fallback"
    original = rows.copy(deep=True)

    recovered = recover_player_rows(rows)
    phase2j = decompose_player_rows(_phase2j_rows(rows))

    assert_frame_equal(rows, original)
    assert recovered["m_tilde"].tolist() == phase2j["positive_mean"].tolist()
    assert recovered["reference"].tolist() == pytest.approx(phase2j["occurrence_surprise"].tolist())
    assert recovered["severity"].tolist() == pytest.approx(phase2j["severity_surprise"].tolist())
    assert recovered["reference_source"].iloc[0] == "pooled_zero_positive_fallback"
    assert recovered["fill_fraction"].iloc[0] == pytest.approx(1.0)


@pytest.mark.parametrize(("attacking", "weight"), [(0.0, 1.0), (6.0, 1.0), (6.0, 2.0)])
def test_sparse_fill_closes_the_exact_identity_with_captain_weight(
    attacking: float, weight: float
) -> None:
    rows = _players()
    rows.loc[0, ["attacking_points", "weight"]] = [attacking, weight]
    rows.loc[0, ["history_attacking_mean", "history_positive_returns"]] = [0.4, 2]
    rows.loc[0, ["positive_mean", "severity_reference_positive_returns"]] = [2.0, 2]
    rows.loc[0, ["recovery_background_mean", "recovery_background_positive_returns"]] = [
        4.0,
        5,
    ]
    rows.loc[0, "recovery_background_source"] = "position_target_excluded"
    original = rows.copy(deep=True)

    recovered = recover_player_rows(rows)
    player = recovered.iloc[0]

    assert_frame_equal(rows, original)
    assert player["m_tilde"] == pytest.approx(3.2)
    assert player["fill_fraction"] == pytest.approx(0.6)
    assert player["reference"] + player["severity"] == pytest.approx(player["attacking_surprise"])
    assert player["attacking_surprise"] == pytest.approx(weight * (attacking - 0.4))
    assert player["target_positive"] == int(attacking > 0.0)


@pytest.mark.parametrize(
    ("position", "other_positions", "other_values", "expected"),
    [
        ("DEF", ["DEF"] * 5, [2.0] * 5, (2.0, 5, "position_target_excluded")),
        ("FWD", ["DEF"] * 5, [3.0] * 5, (3.0, 5, "pooled_target_excluded")),
        ("FWD", ["DEF"] * 4, [3.0] * 4, (float("nan"), 0, "unsupported_sparse_reference")),
    ],
)
def test_sparse_background_uses_position_then_pool_then_unsupported(
    position: str,
    other_positions: list[str],
    other_values: list[float],
    expected: tuple[float, int, str],
) -> None:
    import scripts.run_attacking_support_recovery as runner

    history = pd.DataFrame(
        {
            "player_id": ["target", *range(len(other_values))],
            "position": [position, *other_positions],
            "attacking": [100.0, *other_values],
        }
    )

    mean, count, source = runner._background_reference(
        history, player_id="target", position=position
    )
    expected_mean, expected_count, expected_source = expected
    if np.isnan(expected_mean):
        assert np.isnan(mean)
    else:
        assert mean == pytest.approx(expected_mean)
    assert (count, source) == (expected_count, expected_source)


def test_sparse_reference_excludes_the_player_and_is_independent_of_target_outcome() -> None:
    import scripts.run_attacking_support_recovery as runner

    history = pd.DataFrame(
        {
            "player_id": [1, 1, 1, 2, 3, 4, 5, 6],
            "position": ["MID"] * 8,
            "attacking": [100.0, 100.0, 100.0, 2.0, 2.0, 2.0, 2.0, 2.0],
        }
    )
    first = runner._background_reference(history, player_id=1, position="MID")
    changed_target = history.copy(deep=True)
    changed_target.loc[changed_target["player_id"].eq(1), "attacking"] = 999.0
    second = runner._background_reference(changed_target, player_id=1, position="MID")

    assert first == second == (2.0, 5, "position_target_excluded")


def test_sparse_row_without_a_five_return_reference_excludes_the_fold() -> None:
    rows = _players()
    rows.loc[0, ["history_attacking_mean", "history_positive_returns"]] = [0.4, 2]
    rows.loc[0, ["positive_mean", "severity_reference_positive_returns"]] = [2.0, 2]
    recovered = recover_player_rows(rows)

    assert recovered.loc[0, "supported"] == 0
    assert np.isnan(recovered.loc[0, "reference"])
    reading = build_fold_reading(recovered, 30.0, 35.0, True)
    assert reading["eligible"] is False
    assert reading["supported_starters"] == 10


def test_support_diagnostics_keep_unsupported_sparse_fill_fraction() -> None:
    import scripts.run_attacking_support_recovery as runner

    rows = _players()
    rows.loc[0, ["history_attacking_mean", "history_positive_returns"]] = [0.4, 2]
    rows.loc[0, ["positive_mean", "severity_reference_positive_returns"]] = [2.0, 2]
    recovered = recover_player_rows(rows)
    recovered["carrier_supported"] = recovered["history_positive_returns"].ge(5)
    reading = build_fold_reading(recovered, 30.0, 35.0, True)

    summary = runner._support_summary(recovered, pd.DataFrame([reading]))

    assert summary["fill_fraction"] == {"count": 1, "mean": 0.6, "maximum": 0.6}
    assert summary["reference_source_by_support_bin"]["one_to_four"] == {"unsupported": 1}


def test_fold_reading_uses_the_strict_fixed_q10_event() -> None:
    rows = _recovered_players()
    reading = build_fold_reading(rows, 30.0, 30.0, False)

    assert reading["eligible"] is True
    assert reading["control_below_q10"] is False
    assert reading["identity_error"] == pytest.approx(0.0)
    with pytest.raises(AttackingHurdleError, match="strict q10"):
        build_fold_reading(rows, 30.0, 30.0, True)


def test_summary_reuses_the_canonical_bootstrap_and_is_deterministic() -> None:
    folds = _folds()
    first = summarise(folds)
    second = summarise(folds)
    expected_low, expected_high = bootstrap_interval(
        folds["reference_reduction"].astype(float).tolist(),
        resamples=5000,
        seed=0,
        confidence_level=0.90,
    )

    assert first == second
    reduction = first["parts"]["reference"]["q10_failure_reduction"]
    assert reduction["bootstrap_low"] == pytest.approx(expected_low)
    assert reduction["bootstrap_high"] == pytest.approx(expected_high)
    assert first["parts"]["reference"]["tail_minus_other_surprise"]["bootstrap_high"] < 0


@pytest.mark.parametrize(
    ("reference", "severity", "expected"),
    [
        (True, False, RETURN_REFERENCE_SIGNAL),
        (False, True, POSITIVE_SEVERITY_SIGNAL),
        (True, True, SHARED_REFERENCE_SEVERITY_SIGNAL),
        (False, False, SUPPORT_RECOVERED_NOT_LOCALIZED),
    ],
)
def test_classification_maps_the_frozen_two_part_tree(
    reference: bool, severity: bool, expected: str
) -> None:
    validation = _classification_summary(reference=reference, severity=severity)
    sensitivity = _classification_summary(reference=reference, severity=severity)
    assert classify(validation, sensitivity) == expected


def test_classification_requires_support_and_sensitivity_direction() -> None:
    valid = _classification_summary(reference=True, severity=False)
    unsupported = _classification_summary(reference=True, severity=False, supported=False)
    reversed_sensitivity = _classification_summary(reference=True, severity=False, reverse=True)

    assert classify(unsupported, valid) == INCONCLUSIVE
    assert classify(valid, reversed_sensitivity) == SUPPORT_RECOVERED_NOT_LOCALIZED


def test_runner_recovers_only_one_to_four_rows_and_reuses_other_phase2j_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.run_attacking_support_recovery as runner

    hurdle = _players()
    hurdle.loc[0, ["history_attacking_mean", "history_positive_returns"]] = [0.4, 2]
    hurdle.loc[0, ["positive_mean", "severity_reference_positive_returns"]] = [2.0, 2]
    hurdle = hurdle.drop(
        columns=[
            "recovery_background_mean",
            "recovery_background_positive_returns",
            "recovery_background_source",
        ]
    )
    target = pd.DataFrame(
        {
            "fold_id": ["2023-24-gw10"] * 11,
            "player_id": list(range(1, 12)),
            "position": ["MID"] * 11,
        }
    )
    history = pd.DataFrame(
        {
            "fold_id": ["2023-24-gw09"] * 11,
            "player_id": list(range(1, 12)),
            "position": ["MID"] * 11,
            "attacking": [0.0, *([2.0] * 10)],
        }
    )
    calls: list[object] = []
    original = runner._background_reference

    def recording_reference(
        frame: pd.DataFrame, *, player_id: object, position: str
    ) -> tuple[float, int, str]:
        calls.append(player_id)
        return original(frame, player_id=player_id, position=position)

    monkeypatch.setattr(runner, "_background_reference", recording_reference)
    recovered = runner._recovery_player_rows(hurdle, target, history, ["2023-24-gw09"])

    assert calls == [1]
    assert recovered.loc[0, "recovered_sparse"] == 1
    assert recovered.loc[1:, "recovered_sparse"].eq(0).all()


def test_runner_fails_closed_on_unpinned_phase2j_or_replay_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.run_attacking_support_recovery as runner

    monkeypatch.setattr(runner, "PHASE2J_ARTIFACT", Path("pyproject.toml"))
    with pytest.raises(ValueError, match="pre-registered source"):
        runner._phase2j_document()
    with pytest.raises(ValueError, match="differ"):
        runner._assert_nested_replay(
            {"folds": 30, "mean": 1.0},
            {"folds": 30, "mean": 2.0},
            path="phase2j.replay",
        )

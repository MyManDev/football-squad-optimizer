"""Synthetic tests for chronological fixture-aware recalibration."""

import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import scripts.run_calendar_recalibration as recalibration_cli

from squadopt.recalibration import (
    TIME_AWARE_RECALIBRATION_ARTIFACT_TYPE,
    RecalibrationValidationError,
    TimeAwareRecalibrationConfig,
    run_time_aware_recalibration,
    time_aware_recalibration_to_dict,
    time_aware_recalibration_to_markdown,
)
from squadopt.scenarios.decomposition import decompose_residual_components

SEASON = "2024-25"
PLAYERS = (
    (1, "Alpha", "GK"),
    (2, "Alpha", "DEF"),
    (3, "Beta", "MID"),
    (4, "Beta", "FWD"),
)


def _residuals() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for gameweek in range(2, 12):
        for player_id, team_id, position in PLAYERS:
            reference_residual = float(((gameweek + player_id) % 5) - 2)
            candidate_residual = reference_residual * 0.5
            if gameweek in {3, 5, 9}:
                candidate_residual *= 0.5
            realized = 6.0 + reference_residual
            for candidate, residual in (
                ("calendar_blind_baseline", reference_residual),
                ("calendar_aware_production", candidate_residual),
            ):
                rows.append(
                    {
                        "candidate": candidate,
                        "fold_id": f"{SEASON}-gw{gameweek:02d}",
                        "season": SEASON,
                        "gameweek": gameweek,
                        "player_id": player_id,
                        "team_id": team_id,
                        "position": position,
                        "predicted_points": realized - residual,
                        "realized_points": realized,
                        "residual": residual,
                    }
                )
    return pd.DataFrame(rows)


def _fixtures() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    fixture_id = 0
    for gameweek in range(2, 11):
        repeats = 2 if gameweek in {3, 5, 9} else 1
        for _ in range(repeats):
            fixture_id += 1
            shared: dict[str, object] = {
                "snapshot_id": "archive@test-pin",
                "captured_at_utc": None,
                "season": SEASON,
                "gameweek": gameweek,
                "fixture_id": fixture_id,
                "kickoff_time_utc": f"2024-09-{gameweek + 1:02d}T14:00:00Z",
                "deadline_timestamp_utc": None,
                "status": "final",
                "fixture_difficulty": 3.0,
            }
            rows.extend(
                [
                    {
                        **shared,
                        "team_id": 101,
                        "opponent_team_id": 202,
                        "is_home": True,
                    },
                    {
                        **shared,
                        "team_id": 202,
                        "opponent_team_id": 101,
                        "is_home": False,
                    },
                ]
            )
    frame = pd.DataFrame(rows)
    for column in ("gameweek", "fixture_id", "team_id", "opponent_team_id"):
        frame[column] = frame[column].astype("int64")
    return frame


def _team_codes() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "season": [SEASON, SEASON],
            "name": ["Alpha", "Beta"],
            "code": pd.Series([101, 202], dtype="int64"),
        }
    )


def _config(**overrides: Any) -> TimeAwareRecalibrationConfig:
    values: dict[str, object] = {
        "min_position_observations": 1,
        "min_player_observations": 2,
        "minimum_scale": 0.1,
        "shrinkage_observations": 2.0,
    }
    values.update(overrides)
    return TimeAwareRecalibrationConfig(**values)  # type: ignore[arg-type]


def test_the_three_way_split_is_chronological_and_disjoint() -> None:
    result = run_time_aware_recalibration(_residuals(), _fixtures(), _team_codes(), _config())

    assert result.scale_training_fold_ids == tuple(
        f"{SEASON}-gw{gameweek:02d}" for gameweek in range(2, 6)
    )
    assert result.conformal_calibration_fold_ids == tuple(
        f"{SEASON}-gw{gameweek:02d}" for gameweek in range(6, 9)
    )
    assert result.evaluation_fold_ids == tuple(
        f"{SEASON}-gw{gameweek:02d}" for gameweek in range(9, 12)
    )
    assert not (set(result.scale_training_fold_ids) & set(result.conformal_calibration_fold_ids))
    assert result.diagnostics["evaluation_refit"] is False


def test_held_out_coverage_and_width_are_reported_by_fixture_count() -> None:
    result = run_time_aware_recalibration(_residuals(), _fixtures(), _team_codes(), _config())
    comparisons = {value.fixture_group: value for value in result.interval_comparisons}

    assert tuple(comparisons) == ("overall", "blank", "single", "double_plus")
    assert comparisons["overall"].reference.observations == 12
    assert comparisons["blank"].reference.observations == 4
    assert 0.0 <= comparisons["double_plus"].candidate.empirical_coverage <= 1.0
    assert comparisons["overall"].candidate.mean_interval_width >= 0.0


def test_player_scales_are_refit_for_players_with_double_gameweek_history() -> None:
    result = run_time_aware_recalibration(_residuals(), _fixtures(), _team_codes(), _config())

    assert len(result.player_scale_comparisons) == len(PLAYERS)
    assert all(value.double_plus_observations == 2 for value in result.player_scale_comparisons)
    assert all(
        value.reference_source == "player_shrunk" for value in result.player_scale_comparisons
    )
    assert any(value.scale_delta != 0.0 for value in result.player_scale_comparisons)


def test_scenario_components_are_reestimated_on_pre_evaluation_history() -> None:
    result = run_time_aware_recalibration(_residuals(), _fixtures(), _team_codes(), _config())
    comparison = result.scenario_components

    assert comparison.reference.fold_count == 7
    assert comparison.candidate.fold_count == 7
    assert comparison.reference.observations == 28
    assert sum(
        (
            comparison.candidate.common_variance_share,
            comparison.candidate.team_variance_share,
            comparison.candidate.idiosyncratic_variance_share,
        )
    ) == pytest.approx(1.0)


def test_recalibration_and_scenarios_share_one_exact_decomposition() -> None:
    frame = _residuals().loc[lambda rows: rows["candidate"] == "calendar_aware_production"]
    decomposed = decompose_residual_components(frame)
    recomposed = (
        decomposed["common_component"]
        + decomposed["team_component"]
        + decomposed["idiosyncratic_component"]
    )

    assert recomposed.to_numpy() == pytest.approx(decomposed["residual"].to_numpy())


def test_changing_evaluation_outcomes_does_not_refit_scales_or_components() -> None:
    residuals = _residuals()
    baseline = run_time_aware_recalibration(residuals, _fixtures(), _team_codes(), _config())
    changed = residuals.copy(deep=True)
    mask = (changed["candidate"] == "calendar_aware_production") & changed["gameweek"].ge(9)
    changed.loc[mask, "residual"] = changed.loc[mask, "residual"] + 2.0
    changed.loc[mask, "predicted_points"] = (
        changed.loc[mask, "realized_points"] - changed.loc[mask, "residual"]
    )
    mutated = run_time_aware_recalibration(changed, _fixtures(), _team_codes(), _config())

    assert mutated.player_scale_comparisons == baseline.player_scale_comparisons
    assert mutated.scenario_components == baseline.scenario_components
    assert mutated.interval_comparisons != baseline.interval_comparisons


def test_inputs_are_not_mutated_and_row_order_does_not_change_the_study() -> None:
    residuals = _residuals()
    fixtures = _fixtures()
    team_codes = _team_codes()
    expected_residuals = residuals.copy(deep=True)
    expected_fixtures = fixtures.copy(deep=True)
    expected_codes = team_codes.copy(deep=True)

    first = run_time_aware_recalibration(residuals, fixtures, team_codes, _config())
    shuffled = run_time_aware_recalibration(
        residuals.sample(frac=1.0, random_state=8), fixtures, team_codes, _config()
    )

    pd.testing.assert_frame_equal(residuals, expected_residuals)
    pd.testing.assert_frame_equal(fixtures, expected_fixtures)
    pd.testing.assert_frame_equal(team_codes, expected_codes)
    assert shuffled.study_fingerprint == first.study_fingerprint


def test_report_is_strict_json_and_states_the_opening_boundary() -> None:
    result = run_time_aware_recalibration(_residuals(), _fixtures(), _team_codes(), _config())
    document = time_aware_recalibration_to_dict(result)
    markdown = time_aware_recalibration_to_markdown(result)

    json.dumps(document, allow_nan=False)
    assert document["artifact_type"] == TIME_AWARE_RECALIBRATION_ARTIFACT_TYPE
    assert document["study_fingerprint"] == result.study_fingerprint
    assert "Held-out conformal coverage" in markdown
    assert "Opening-gameweek uncertainty remains unavailable" in markdown


@pytest.mark.parametrize(
    "kwargs",
    [
        {"confidence_level": 1.0},
        {"scale_training_fraction": 0.8, "conformal_calibration_fraction": 0.3},
        {"min_player_observations": 0},
        {"minimum_scale": 0.0},
    ],
)
def test_invalid_study_configuration_is_rejected(kwargs: dict[str, object]) -> None:
    with pytest.raises(RecalibrationValidationError):
        _config(**kwargs)


def test_at_least_three_chronological_folds_are_required() -> None:
    residuals = _residuals()
    residuals = residuals.loc[residuals["gameweek"].isin([2, 3])]

    with pytest.raises(RecalibrationValidationError, match="at least three"):
        run_time_aware_recalibration(residuals, _fixtures(), _team_codes(), _config())


def test_cli_time_aware_mode_writes_the_versioned_study(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    residuals = _residuals()
    reference_path = tmp_path / "reference.csv"
    candidate_path = tmp_path / "candidate.csv"
    json_path = tmp_path / "study.json"
    residuals.loc[residuals["candidate"] == "calendar_blind_baseline"].drop(
        columns="candidate"
    ).to_csv(reference_path, index=False)
    residuals.loc[residuals["candidate"] == "calendar_aware_production"].drop(
        columns="candidate"
    ).to_csv(candidate_path, index=False)
    monkeypatch.setattr(
        recalibration_cli, "build_fixture_panel", lambda *_args, **_kwargs: _fixtures()
    )
    monkeypatch.setattr(
        recalibration_cli,
        "load_team_codes",
        lambda *_args, **_kwargs: _team_codes().drop(columns="season"),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_calendar_recalibration",
            "--reference-residuals",
            str(reference_path),
            "--candidate-residuals",
            str(candidate_path),
            "--time-aware",
            "--min-position-observations",
            "1",
            "--min-player-observations",
            "2",
            "--minimum-scale",
            "0.1",
            "--json-output",
            str(json_path),
        ],
    )

    assert recalibration_cli.main() == 0
    document = json.loads(json_path.read_text(encoding="utf-8"))
    assert document["artifact_type"] == TIME_AWARE_RECALIBRATION_ARTIFACT_TYPE
    assert document["chronological_split"]["evaluation_fold_ids"]

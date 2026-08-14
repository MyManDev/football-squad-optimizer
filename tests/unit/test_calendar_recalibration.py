"""Synthetic contract tests for calendar-aware residual measurement."""

import json
import sys
from pathlib import Path

import pandas as pd
import pytest
import scripts.run_calendar_recalibration as recalibration_cli

from squadopt.recalibration import (
    CALENDAR_RECALIBRATION_ARTIFACT_TYPE,
    CALENDAR_RECALIBRATION_CONTRACT_VERSION,
    CALENDAR_RECALIBRATION_REPORT_SCHEMA_VERSION,
    RecalibrationConfig,
    RecalibrationValidationError,
    measure_calendar_recalibration,
    recalibration_to_dict,
    recalibration_to_markdown,
    validate_residual_regimes,
)

SEASON = "2024-25"
SNAPSHOT = "archive@test-pin"


def _fixture(
    fixture_id: int,
    gameweek: int,
    home: int,
    away: int,
) -> list[dict[str, object]]:
    common: dict[str, object] = {
        "snapshot_id": SNAPSHOT,
        "captured_at_utc": None,
        "season": SEASON,
        "gameweek": gameweek,
        "fixture_id": fixture_id,
        "kickoff_time_utc": f"2024-09-{gameweek + 1:02d}T14:00:00Z",
        "deadline_timestamp_utc": None,
        "status": "final",
        "fixture_difficulty": 3.0,
    }
    return [
        {
            **common,
            "team_id": home,
            "opponent_team_id": away,
            "is_home": True,
        },
        {
            **common,
            "team_id": away,
            "opponent_team_id": home,
            "is_home": False,
        },
    ]


@pytest.fixture
def fixtures() -> pd.DataFrame:
    rows = [
        *_fixture(1, 2, 101, 202),
        *_fixture(2, 2, 303, 404),
        *_fixture(3, 3, 101, 202),
        *_fixture(4, 3, 303, 101),
        *_fixture(5, 4, 202, 303),
    ]
    frame = pd.DataFrame(rows)
    for column in ("gameweek", "fixture_id", "team_id", "opponent_team_id"):
        frame[column] = frame[column].astype("int64")
    return frame


@pytest.fixture
def team_codes() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "season": [SEASON] * 4,
            "name": ["Alpha", "Beta", "Gamma", "Delta"],
            "code": pd.Series([101, 202, 303, 404], dtype="int64"),
        }
    )


@pytest.fixture
def residuals() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    regimes = {
        "calendar_blind_baseline": [(2, 5.0, 5.0), (3, 3.0, 5.0), (4, 6.0, 5.0)],
        "calendar_aware_production": [(2, 5.0, 5.0), (3, 5.0, 5.0), (4, 5.5, 5.0)],
    }
    for candidate, values in regimes.items():
        for gameweek, predicted, realized in values:
            rows.append(
                {
                    "candidate": candidate,
                    "fold_id": f"{SEASON}-gw{gameweek:02d}",
                    "season": SEASON,
                    "gameweek": gameweek,
                    "player_id": 9001,
                    "team_id": "Alpha",
                    "position": "MID",
                    "predicted_points": predicted,
                    "realized_points": realized,
                    "residual": realized - predicted,
                }
            )
    return pd.DataFrame(rows)


def test_fixture_context_distinguishes_blank_single_and_double_gameweeks(
    residuals: pd.DataFrame,
    fixtures: pd.DataFrame,
    team_codes: pd.DataFrame,
) -> None:
    result = measure_calendar_recalibration(residuals, fixtures, team_codes)
    reference = result.residuals_with_fixture_context.loc[
        result.residuals_with_fixture_context["candidate"] == "calendar_blind_baseline"
    ]

    assert reference["fixture_count"].tolist() == [1, 2, 0]
    assert reference["fixture_group"].tolist() == ["single", "double_plus", "blank"]
    assert result.diagnostics["fixture_group_counts"] == {
        "blank": 1,
        "single": 1,
        "double_plus": 1,
    }


def test_measurement_is_matched_and_reports_candidate_minus_reference_deltas(
    residuals: pd.DataFrame,
    fixtures: pd.DataFrame,
    team_codes: pd.DataFrame,
) -> None:
    result = measure_calendar_recalibration(residuals, fixtures, team_codes)
    by_group = {entry.fixture_group: entry for entry in result.comparisons}

    assert tuple(by_group) == ("overall", "blank", "single", "double_plus")
    assert by_group["overall"].observations == 3
    assert by_group["double_plus"].reference.mean_absolute_error == pytest.approx(2.0)
    assert by_group["double_plus"].candidate.mean_absolute_error == pytest.approx(0.0)
    assert by_group["double_plus"].mean_absolute_error_delta == pytest.approx(-2.0)


def test_inputs_are_not_mutated_and_fingerprint_is_stable(
    residuals: pd.DataFrame,
    fixtures: pd.DataFrame,
    team_codes: pd.DataFrame,
) -> None:
    original_residuals = residuals.copy(deep=True)
    original_fixtures = fixtures.copy(deep=True)
    original_codes = team_codes.copy(deep=True)

    first = measure_calendar_recalibration(residuals, fixtures, team_codes)
    second = measure_calendar_recalibration(
        residuals.sample(frac=1.0, random_state=7), fixtures, team_codes
    )

    pd.testing.assert_frame_equal(residuals, original_residuals)
    pd.testing.assert_frame_equal(fixtures, original_fixtures)
    pd.testing.assert_frame_equal(team_codes, original_codes)
    assert first.measurement_fingerprint == second.measurement_fingerprint


def test_duplicate_candidate_fold_player_rows_are_rejected(residuals: pd.DataFrame) -> None:
    duplicated = pd.concat([residuals, residuals.iloc[[0]]], ignore_index=True)

    with pytest.raises(RecalibrationValidationError, match="at most one row"):
        validate_residual_regimes(duplicated, RecalibrationConfig())


def test_unmatched_residual_regimes_are_rejected(residuals: pd.DataFrame) -> None:
    unmatched = residuals.drop(index=residuals.index[-1])

    with pytest.raises(RecalibrationValidationError, match="identical fold/player rows"):
        validate_residual_regimes(unmatched, RecalibrationConfig())


def test_residual_formula_is_verified(residuals: pd.DataFrame) -> None:
    invalid = residuals.copy(deep=True)
    invalid.loc[0, "residual"] = 99.0

    with pytest.raises(RecalibrationValidationError, match="realized_points minus"):
        validate_residual_regimes(invalid, RecalibrationConfig())


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda frame: frame.drop(columns="position"), "missing columns"),
        (lambda frame: frame.assign(team_id=pd.NA), "missing values"),
        (lambda frame: frame.assign(candidate="unexpected"), "exactly candidates"),
    ],
)
def test_malformed_residual_contract_is_rejected(
    residuals: pd.DataFrame,
    mutation: object,
    message: str,
) -> None:
    transform = mutation
    assert callable(transform)
    with pytest.raises(RecalibrationValidationError, match=message):
        validate_residual_regimes(transform(residuals), RecalibrationConfig())


def test_paired_rows_must_agree_on_invariant_fields(residuals: pd.DataFrame) -> None:
    invalid = residuals.copy(deep=True)
    candidate = invalid["candidate"] == "calendar_aware_production"
    invalid.loc[candidate & invalid["gameweek"].eq(2), "position"] = "FWD"

    with pytest.raises(RecalibrationValidationError, match="invariant column 'position'"):
        validate_residual_regimes(invalid, RecalibrationConfig())


def test_fixture_join_refuses_an_unknown_team(
    residuals: pd.DataFrame,
    fixtures: pd.DataFrame,
    team_codes: pd.DataFrame,
) -> None:
    unknown = residuals.assign(team_id="Unknown")

    with pytest.raises(RecalibrationValidationError, match="could not be attached"):
        measure_calendar_recalibration(unknown, fixtures, team_codes)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"reference_candidate": ""},
        {"candidate": "calendar_blind_baseline"},
        {"contract_version": "future"},
    ],
)
def test_invalid_configuration_is_rejected(kwargs: dict[str, str]) -> None:
    with pytest.raises(RecalibrationValidationError):
        RecalibrationConfig(**kwargs)


def test_json_and_markdown_reports_state_the_measurement_boundary(
    residuals: pd.DataFrame,
    fixtures: pd.DataFrame,
    team_codes: pd.DataFrame,
) -> None:
    result = measure_calendar_recalibration(residuals, fixtures, team_codes)
    document = recalibration_to_dict(result)
    markdown = recalibration_to_markdown(result)

    json.dumps(document, allow_nan=False)
    assert document["artifact_type"] == CALENDAR_RECALIBRATION_ARTIFACT_TYPE
    assert document["report_schema_version"] == (CALENDAR_RECALIBRATION_REPORT_SCHEMA_VERSION)
    assert document["contract_version"] == CALENDAR_RECALIBRATION_CONTRACT_VERSION
    assert document["diagnostics"]["conformal_recalibrated"] is False  # type: ignore[index]
    assert document["diagnostics"]["fixture_contract_version"] == (  # type: ignore[index]
        "fixture_snapshot_v1"
    )
    assert len(document["diagnostics"]["residual_fingerprints"]) == 2  # type: ignore[index]
    assert "does not yet claim conformal" in document["limitations"][0]  # type: ignore[index]
    assert "Scope boundary" in markdown
    assert CALENDAR_RECALIBRATION_REPORT_SCHEMA_VERSION in markdown
    assert "double_plus" in markdown
    assert "Opening-gameweek uncertainty is a separate regime" in markdown


def test_cli_writes_deterministic_json_and_markdown_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    residuals: pd.DataFrame,
    fixtures: pd.DataFrame,
    team_codes: pd.DataFrame,
) -> None:
    reference_path = tmp_path / "reference.csv"
    candidate_path = tmp_path / "candidate.csv"
    json_path = tmp_path / "measurement.json"
    markdown_path = tmp_path / "measurement.md"
    residuals.loc[residuals["candidate"] == "calendar_blind_baseline"].drop(
        columns="candidate"
    ).to_csv(reference_path, index=False)
    residuals.loc[residuals["candidate"] == "calendar_aware_production"].drop(
        columns="candidate"
    ).to_csv(candidate_path, index=False)

    monkeypatch.setattr(
        recalibration_cli, "build_fixture_panel", lambda *_args, **_kwargs: fixtures
    )
    monkeypatch.setattr(
        recalibration_cli,
        "load_team_codes",
        lambda *_args, **_kwargs: team_codes.drop(columns="season"),
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
            "--json-output",
            str(json_path),
            "--markdown-output",
            str(markdown_path),
        ],
    )

    assert recalibration_cli.main() == 0
    document = json.loads(json_path.read_text(encoding="utf-8"))
    assert document["measurement_fingerprint"]
    assert markdown_path.read_text(encoding="utf-8").startswith(
        "# Calendar-aware residual measurement"
    )

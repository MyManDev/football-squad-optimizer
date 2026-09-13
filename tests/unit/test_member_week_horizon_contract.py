"""Python producers can validate the optional horizon without importing the web app."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

SCHEMA = json.loads(
    (Path(__file__).parents[2] / "docs/contracts/member_week_horizon_v1.schema.json").read_text(
        encoding="utf-8"
    )
)
MEASUREMENT = {
    "contract_version": "member_week_horizon_v1",
    "season": "2026-27",
    "league_id": 352490,
    "scoring_basis": "official_autosub_captain_v2",
    "population": "recorded_member_suggestions_vs_actual",
    "measurement_artifact": "docs/member_week_measurement.json",
    "within_week_correlation": 0.3,
    "required_week_clusters": 20,
    "member_week_keys": [f"101:{week}:{'a' * 64}:capture-{week}" for week in (4, 5)],
}


def test_the_measurement_handoff_has_a_valid_python_readable_schema() -> None:
    Draft202012Validator.check_schema(SCHEMA)
    Draft202012Validator(SCHEMA).validate(MEASUREMENT)


@pytest.mark.parametrize("field", list(MEASUREMENT))
def test_every_declared_measurement_field_is_required(field: str) -> None:
    incomplete = {name: value for name, value in MEASUREMENT.items() if name != field}
    with pytest.raises(ValidationError):
        Draft202012Validator(SCHEMA).validate(incomplete)


@pytest.mark.parametrize(
    "changes",
    [
        {"within_week_correlation": None},
        {"within_week_correlation": "0"},
        {"within_week_correlation": True},
        {"within_week_correlation": -1.01},
        {"within_week_correlation": 1.01},
        {"required_week_clusters": 0},
        {"required_week_clusters": 1},
        {"required_week_clusters": 2.5},
        {"required_week_clusters": None},
        {"member_week_keys": []},
        {"member_week_keys": ["same-record", "same-record"]},
        {"scoring_basis": "named_eleven_no_autosubs"},
        {"population": "paper_ledger"},
        {"measurement_artifact": "https://example.com/measurement.json"},
    ],
)
def test_unavailable_or_invalid_measurements_are_not_numeric_targets(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        Draft202012Validator(SCHEMA).validate({**MEASUREMENT, **changes})


@pytest.mark.parametrize("correlation", [-1, 0, 1])
def test_a_recorded_zero_or_boundary_correlation_is_valid(correlation: int) -> None:
    Draft202012Validator(SCHEMA).validate({**MEASUREMENT, "within_week_correlation": correlation})

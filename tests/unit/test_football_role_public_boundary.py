"""The public role explanation cannot promote internal model probabilities."""

from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator

from squadopt.application.football_roles import role_forecast_summary
from squadopt.contracts.football_explanations import role_forecast_schema

MODELED_FIELDS = (
    "start_probability",
    "cameo_probability",
    "zero_probability",
    "unknown_role_probability",
    "sixty_minute_probability",
)
PUBLIC_FIELDS = {
    "player_id",
    "name",
    "fixture_id",
    "gameweek",
    "kickoff",
    "status",
    "expected_minutes",
    "captured_eligibility_multiplier",
    "news_applied",
}


def internal_row(*, unknown=False, breakdown=True):
    row = {
        "player_id": 123,
        "name": "Test player",
        "fixture_id": 9999,
        "gameweek": 6,
        "kickoff": "2026-10-11T12:30:00Z",
        "status": "unavailable_no_known_start_labels" if unknown else "fitted_known_start_labels",
        "start_probability": None if unknown else 0.4,
        "cameo_probability": None if unknown else 0.1,
        "zero_probability": 0.5,
        "unknown_role_probability": 0.5 if unknown else 0.0,
        "expected_minutes": 34.0,
        "sixty_minute_probability": 0.3,
        "captured_eligibility_multiplier": 0.5,
        "news_applied": True,
        "future_internal_diagnostic": "never publish",
    }
    if breakdown:
        row["point_components"] = {
            "appearance": 0.8,
            "goals": 0.5,
            "assists": 0.3,
            "clean_sheet": 0.5,
            "defcon": 0.2,
            "other": -0.1,
            "clipping": 0.0,
            "total": 2.2,
        }
    return row


@pytest.mark.parametrize("unknown", [False, True])
@pytest.mark.parametrize("breakdown", [False, True])
def test_summary_keeps_minutes_points_and_source_facts_but_no_modeled_probabilities(
    unknown, breakdown
):
    row = internal_row(unknown=unknown, breakdown=breakdown)
    diagnostics = {"fixture_role_estimates": [row, {**row, "player_id": 456}]}
    before = deepcopy(diagnostics)
    summary = role_forecast_summary(diagnostics, {123})
    assert summary is not None
    Draft202012Validator(role_forecast_schema()).validate(summary)
    assert summary["calibration"] == "not_independently_verified"
    assert len(summary["rows"]) == 1
    published = summary["rows"][0]
    expected_keys = PUBLIC_FIELDS | ({"point_components"} if breakdown else set())
    assert set(published) == expected_keys
    assert published == {key: row[key] for key in expected_keys}
    assert published["expected_minutes"] == 34.0
    assert published["captured_eligibility_multiplier"] == 0.5
    assert published["status"] == row["status"]
    assert not set(MODELED_FIELDS).intersection(published)
    # The numerical law used by the optimizer is untouched by public serialization.
    assert diagnostics == before
    assert published is not row


@pytest.mark.parametrize("field", MODELED_FIELDS)
def test_public_schema_rejects_each_modeled_probability_even_if_numeric_and_in_range(field):
    summary = role_forecast_summary({"fixture_role_estimates": [internal_row()]}, {123})
    assert summary is not None
    summary["rows"][0][field] = 0.5
    assert list(Draft202012Validator(role_forecast_schema()).iter_errors(summary))


def test_no_selected_role_rows_means_no_public_explanation():
    assert role_forecast_summary({}, {123}) is None
    assert role_forecast_summary({"fixture_role_estimates": [internal_row()]}, {456}) is None

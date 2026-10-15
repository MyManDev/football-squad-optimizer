"""Nested fields must be safe to consume in both API and browser."""

import json

import pytest
from tests.unit.test_advice_read import _valid_advice_document

from squadopt.platform.advice_documents import AdviceDocumentError, validate_advice_document


@pytest.mark.parametrize(
    "patch",
    [
        {"moves": [None]},
        {"captain": {"player_id": True}},
        {"bench": [None]},
        {"plan_weeks": [{"gameweek": 1}]},
        {"missing_fields": [None]},
        {"expected_points_cost": float("inf")},
        {"data_quality": "invented"},
        {"window": 1.5},
        {"alternative_plan": {"kind": "with_hits"}},
    ],
)
def test_malformed_nested_fields_are_not_served(patch: dict) -> None:
    document = json.loads(_valid_advice_document())
    document["payload"].update(patch)
    with pytest.raises(AdviceDocumentError):
        validate_advice_document(json.dumps(document).encode())


def test_json_number_overflow_is_not_a_finite_prediction() -> None:
    raw = _valid_advice_document().replace(
        b'"moves": []', b'"expected_points_cost": 1e400, "moves": []'
    )
    with pytest.raises(AdviceDocumentError):
        validate_advice_document(raw)


@pytest.mark.parametrize(
    "version",
    [
        "football_joint_role_minutes_v1",
        "football_joint_role_retained_history_v1",
        "football_joint_role_retained_flags_v1",
        "football_composite_v1",
    ],
)
def test_football_model_and_role_breakdown_cross_the_advice_boundary(version: str) -> None:
    document = json.loads(_valid_advice_document())
    payload = document["payload"]
    payload["prediction_model"] = {
        "id": "football",
        "version": version,
        "experimental": True,
        "fingerprint": "a" * 64,
    }
    payload["role_forecast"] = {
        "version": "football_role_forecast_v1",
        "model_version": version,
        "calibration": "not_independently_verified",
        "scope": "current_gameweek_fixtures",
        "rows": [
            {
                "player_id": 1,
                "name": "Player",
                "fixture_id": 61,
                "gameweek": 7,
                "kickoff": "2026-10-17T14:00:00Z",
                "status": "fitted_known_start_labels",
                "captured_eligibility_multiplier": 1.0,
                "expected_minutes": 34.0,
                "news_applied": False,
                "point_components": {
                    "appearance": 1.0,
                    "goals": 0.5,
                    "assists": 0.2,
                    "clean_sheet": 0.1,
                    "defcon": 0.0,
                    "other": -0.1,
                    "clipping": 0.0,
                    "total": 1.7,
                },
            }
        ],
    }
    raw = json.dumps(document).encode()
    validate_advice_document(raw)
    for section, field in (
        ("prediction_model", "version"),
        ("role_forecast", "model_version"),
    ):
        payload[section][field] = "unknown_model_v1"
        with pytest.raises(AdviceDocumentError):
            validate_advice_document(json.dumps(document).encode())
        payload[section][field] = version

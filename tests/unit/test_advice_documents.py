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

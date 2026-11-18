"""The private device extension keeps counts, resources and nesting bounded."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

from squadopt.contracts.llmopt_device import device_extension_schema


def test_device_extension_schema_is_committed():
    path = Path(__file__).parents[2] / "docs/contracts/llmopt_device_v1.schema.json"
    assert json.loads(path.read_text(encoding="utf-8")) == device_extension_schema()


@pytest.mark.parametrize(
    "value",
    [
        {"free_transfers_after": 6},
        {"free_transfers_before": -1},
        {"bank_after_tenths": -1},
        {"device_alternatives": [{}, {}, {}]},
        {"alternatives": [{}, {}, {}]},
        {"device_alternatives": [{"device_alternatives": []}]},
        {"alternatives": [{"alternatives": []}]},
        {"device_input_fingerprint": "old"},
    ],
)
def test_invalid_device_extension_is_rejected(value):
    with pytest.raises(ValidationError):
        Draft202012Validator(device_extension_schema()).validate(value)


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"alternatives": True},
        {"alternatives": []},
        {"device_alternatives": [{}, {}], "free_transfers_after": 5, "bank_after_tenths": 0},
        {"device_input_fingerprint": "a" * 64},
    ],
)
def test_legacy_and_bounded_device_extensions_remain_valid(value):
    Draft202012Validator(device_extension_schema()).validate(value)

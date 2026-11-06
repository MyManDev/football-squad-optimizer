"""The optional activity view preserves the strict score contract and closes event fields."""

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

CONTRACTS = Path(__file__).resolve().parents[2] / "docs" / "contracts"
SCHEMA = json.loads((CONTRACTS / "week_activity_v1.schema.json").read_text(encoding="utf-8"))
EXAMPLES = json.loads((CONTRACTS / "week_activity_v1.examples.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", sorted(EXAMPLES))
def test_activity_examples_follow_the_closed_contract(name: str) -> None:
    Draft202012Validator.check_schema(SCHEMA)
    Draft202012Validator(SCHEMA).validate(EXAMPLES[name])


def test_embedded_score_is_the_unmodified_live_contract() -> None:
    live = json.loads((CONTRACTS / "week_live_v1.schema.json").read_text(encoding="utf-8"))
    assert SCHEMA["$defs"]["week"] == {
        key: value for key, value in live.items() if key not in ("$schema", "$defs")
    }
    for key, definition in live["$defs"].items():
        assert SCHEMA["$defs"][key] == definition


@pytest.mark.parametrize("value", [-1, 1.5, True, "1"])
def test_event_counts_must_be_nonnegative_integers(value: object) -> None:
    document = copy.deepcopy(EXAMPLES["in_progress"])
    document["activity"]["appearances"][0]["goals"] = value
    with pytest.raises(ValidationError):
        Draft202012Validator(SCHEMA).validate(document)


def test_raw_upstream_fields_do_not_belong_to_the_contract() -> None:
    document = copy.deepcopy(EXAMPLES["in_progress"])
    document["activity"]["appearances"][0]["raw"] = "unexpected"
    with pytest.raises(ValidationError):
        Draft202012Validator(SCHEMA).validate(document)

"""The live-score wire contract has synthetic progress and finished examples."""

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker, ValidationError

CONTRACTS = Path(__file__).resolve().parents[2] / "docs" / "contracts"
SCHEMA = json.loads((CONTRACTS / "week_live_v1.schema.json").read_text(encoding="utf-8"))
EXAMPLES = json.loads((CONTRACTS / "week_live_v1.examples.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("state", ["in_progress", "finished"])
def test_progress_and_finished_examples_match_live_and_member_shapes(state):
    Draft202012Validator.check_schema(SCHEMA)
    validator = Draft202012Validator(SCHEMA, format_checker=FormatChecker())
    example = EXAMPLES[state]
    validator.validate(example)
    assert all(fixture["finished"] for fixture in example["fixtures"]) is (state == "finished")
    member_schema = {"$ref": "#/$defs/memberWeek", "$defs": SCHEMA["$defs"]}
    member_validator = Draft202012Validator(member_schema)
    for member in example["members"]:
        member_validator.validate(member)
        assert member["gameweek"] == example["gameweek"]
        assert set(member["pick_order"]) <= {item["element_id"] for item in example["elements"]}
    trimmed = copy.deepcopy(example)
    del trimmed["members"]
    for element in trimmed["elements"]:
        del element["position"], element["club"]
    validator.validate(trimmed)


@pytest.mark.parametrize(
    "damage",
    [
        lambda item: item.update(contract_version="live_score_v1"),
        lambda item: item.update(source_time="2026-10-10"),
        lambda item: item.update(source_time="2026-10-10T20:00:00+03:00"),
        lambda item: item["fixtures"][0].update(finished="true"),
        lambda item: item["elements"][0].update(minutes=True),
        lambda item: item["elements"][0].update(points=1.5),
        lambda item: item["elements"][0].update(card_shown=1),
        lambda item: item["elements"][0].update(raw_response="private"),
        lambda item: item["members"][0].update(active_chip="unknown"),
        lambda item: item["members"][0].update(transfer_cost=-4),
        lambda item: item["members"][0]["pick_order"].pop(),
        lambda item: item["members"][0]["pick_order"].__setitem__(1, 1),
    ],
)
def test_wire_contract_refuses_malformed_or_unrequested_values(damage):
    example = copy.deepcopy(EXAMPLES["in_progress"])
    damage(example)
    with pytest.raises(ValidationError):
        Draft202012Validator(SCHEMA, format_checker=FormatChecker()).validate(example)

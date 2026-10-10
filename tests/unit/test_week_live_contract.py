"""The live-score wire contract has synthetic progress and finished examples."""

import copy
import json
from collections import Counter
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
        picked = {item["element_id"]: item for item in example["elements"]}
        assert (
            max(Counter(picked[element]["club"] for element in member["pick_order"]).values()) <= 3
        )
        positions = Counter(picked[element]["position"] for element in member["pick_order"])
        assert positions == {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}
        eleven = Counter(picked[element]["position"] for element in member["pick_order"][:11])
        assert eleven["GK"] == 1 and 3 <= eleven["DEF"] <= 5
        assert 2 <= eleven["MID"] <= 5 and 1 <= eleven["FWD"] <= 3
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
        lambda item: item.update(source_time="garbageZ"),
        lambda item: item.update(source_time="2026-13-45T99:99:99Z"),
        lambda item: item.update(source_time="Z"),
        lambda item: item["fixtures"][0].update(finished="true"),
        lambda item: item["elements"][0].update(minutes=True),
        lambda item: item["elements"][0].update(points=1.5),
        lambda item: item["elements"][0].update(card_shown=1),
        lambda item: item["elements"][0].update(raw_response="private"),
        lambda item: item["members"][0].update(active_chip="unknown"),
        lambda item: item["members"][0].update(transfer_cost=-4),
        lambda item: item["members"][0]["pick_order"].pop(),
        lambda item: item["members"][0]["pick_order"].__setitem__(1, 1),
        lambda item: item["members"][0].update(player_name="x"),
        lambda item: item.update(private_field="x"),
        lambda item: item["fixtures"][0].update(private_field="x"),
        lambda item: item["elements"][0].update(minutes=-1),
        lambda item: item["members"][0]["pick_order"].append(16),
        lambda item: item["elements"][0].pop("card_shown"),
        lambda item: item["members"][0].update(captain="7"),
        lambda item: item.update(gameweek=39),
    ],
)
def test_wire_contract_refuses_malformed_or_unrequested_values(damage):
    example = copy.deepcopy(EXAMPLES["in_progress"])
    damage(example)
    with pytest.raises(ValidationError):
        Draft202012Validator(SCHEMA, format_checker=FormatChecker()).validate(example)


def test_progress_example_contains_absence_pending_bench_and_pending_vice():
    example = EXAMPLES["in_progress"]
    elements = {item["element_id"]: item for item in example["elements"]}
    member = example["members"][0]

    def complete(element):
        return all(
            fixture["finished"]
            for fixture in example["fixtures"]
            if element["club"] in (fixture["home_club"], fixture["away_club"])
        )

    absent = elements[2]
    assert complete(absent) and absent["minutes"] == 0 and not absent["card_shown"]
    first_reserve = elements[member["pick_order"][12]]
    assert not complete(first_reserve)
    assert first_reserve["minutes"] == 0 and not first_reserve["card_shown"]
    assert elements[member["pick_order"][13]]["minutes"] > 0
    captain, vice = elements[member["captain"]], elements[member["vice"]]
    assert complete(captain) and captain["minutes"] == 0
    assert not complete(vice) and vice["minutes"] == 0
    assert member["vice"] in member["pick_order"][:11]


def test_finished_example_settles_the_progress_example_inputs():
    progress, finished = EXAMPLES["in_progress"], EXAMPLES["finished"]
    assert progress["members"] == finished["members"]
    assert [
        {key: value for key, value in fixture.items() if key != "finished"}
        for fixture in progress["fixtures"]
    ] == [
        {key: value for key, value in fixture.items() if key != "finished"}
        for fixture in finished["fixtures"]
    ]
    settled = {item["element_id"]: item for item in finished["elements"]}
    assert settled.keys() == {item["element_id"] for item in progress["elements"]}
    pending_clubs = {
        club
        for fixture in progress["fixtures"]
        if not fixture["finished"]
        for club in (fixture["home_club"], fixture["away_club"])
    }
    completed = [item for item in progress["elements"] if item["club"] not in pending_clubs]
    assert completed
    for element in completed:
        assert element == settled[element["element_id"]]

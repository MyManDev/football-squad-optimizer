"""The FPL forwarder's two documents have closed schemas and synthetic examples (#980, ADR 0012).

The forwarder in `workers/fpl-proxy` answers `fpl_league_standings_v1` and
`fpl_entry_bundle_v1`. Its node tests build both from synthetic FPL-shaped answers and require
the result to equal the committed examples; this test holds the examples to the schemas with
jsonschema itself, and holds the bundle's member week to `week_live_v1`'s, so the block a
bundle carries is the block the live scorer reads.
"""

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker, ValidationError

CONTRACTS = Path(__file__).resolve().parents[2] / "docs" / "contracts"


def _load(name: str) -> dict:
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


STANDINGS = _load("fpl_league_standings_v1.schema.json")
STANDINGS_EXAMPLES = _load("fpl_league_standings_v1.examples.json")
BUNDLE = _load("fpl_entry_bundle_v1.schema.json")
BUNDLE_EXAMPLES = _load("fpl_entry_bundle_v1.examples.json")
WEEK_LIVE = _load("week_live_v1.schema.json")


def _validator(schema: dict) -> Draft202012Validator:
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


@pytest.mark.parametrize("name", sorted(STANDINGS_EXAMPLES))
def test_standings_examples_match_the_schema(name):
    example = STANDINGS_EXAMPLES[name]
    _validator(STANDINGS).validate(example)
    assert example["contract_version"] == "fpl_league_standings_v1"
    assert example["league"]["scoring"] == "classic"
    ranks = [row["rank_sort"] for row in example["results"]]
    assert ranks == sorted(ranks) and len(set(ranks)) == len(ranks)


def test_standings_pages_are_one_league_continued():
    first, last = STANDINGS_EXAMPLES["first_page"], STANDINGS_EXAMPLES["last_page"]
    assert first["league"] == last["league"]
    assert (first["page"], first["has_next"]) == (1, True)
    assert (last["page"], last["has_next"]) == (2, False)
    assert first["last_updated_data"] == last["last_updated_data"]


@pytest.mark.parametrize("name", sorted(BUNDLE_EXAMPLES))
def test_bundle_examples_match_the_schema(name):
    example = BUNDLE_EXAMPLES[name]
    _validator(BUNDLE).validate(example)
    assert example["contract_version"] == "fpl_entry_bundle_v1"
    assert example["entry"]["id"] == example["entry_id"]
    weeks = [picks["entry_history"]["event"] for picks in example["picks"]]
    assert weeks == sorted(set(weeks))
    assert max(weeks) == example["gameweek"] - 1
    for picks in example["picks"]:
        assert sorted(row["position"] for row in picks["picks"]) == list(range(1, 16))


def test_bundle_examples_cover_the_free_hit_walk_back_and_a_late_joiner():
    walk = BUNDLE_EXAMPLES["free_hit_walk_back"]
    assert [picks["entry_history"]["event"] for picks in walk["picks"]] == [1, 8, 9]
    assert [picks["active_chip"] for picks in walk["picks"]] == [None, None, "freehit"]
    late = BUNDLE_EXAMPLES["late_joiner"]
    assert late["entry"]["started_event"] == 4
    assert [picks["entry_history"]["event"] for picks in late["picks"]] == [9]
    held = late["picks"][0]
    substitution = held["automatic_subs"][0]
    position = {row["element"]: row["position"] for row in held["picks"]}
    # FPL's own positions are kept in the picks; the member week names the deadline's order.
    assert position[substitution["element_in"]] <= 11 < position[substitution["element_out"]]
    order = late["current_week"]["pick_order"]
    assert order.index(substitution["element_out"]) < 11 <= order.index(substitution["element_in"])


def test_the_bundle_member_week_is_week_live_v1s():
    for name in ("memberWeek", "id", "gameweek"):
        assert BUNDLE["$defs"][name] == WEEK_LIVE["$defs"][name], name
    member = {"$ref": "#/$defs/memberWeek", "$defs": WEEK_LIVE["$defs"]}
    for example in BUNDLE_EXAMPLES.values():
        Draft202012Validator(member).validate(example["current_week"])
        assert example["current_week"]["entry_id"] == example["entry_id"]


@pytest.mark.parametrize(
    "damage",
    [
        lambda item: item.update(contract_version="fpl_league_standings_v2"),
        lambda item: item.update(page=21),
        lambda item: item.update(page=0),
        lambda item: item.update(source_time="2026-10-19"),
        lambda item: item.update(raw_response="private"),
        lambda item: item["league"].update(id=0),
        lambda item: item["league"].update(scoring="h2h"),
        lambda item: item["league"].update(admin_entry=1),
        lambda item: item["results"][0].update(entry=-1),
        lambda item: item["results"][0].update(total=1.5),
        lambda item: item["results"][0].update(player_first_name="private"),
        lambda item: item["results"][0].pop("event_total"),
    ],
)
def test_standings_schema_refuses_malformed_or_unrequested_values(damage):
    example = copy.deepcopy(STANDINGS_EXAMPLES["first_page"])
    damage(example)
    with pytest.raises(ValidationError):
        _validator(STANDINGS).validate(example)


@pytest.mark.parametrize(
    "damage",
    [
        lambda item: item.update(contract_version="week_live_v1"),
        lambda item: item.update(gameweek=1),
        lambda item: item.update(gameweek=39),
        lambda item: item.update(entry_id=True),
        lambda item: item.update(raw_response="private"),
        lambda item: item["entry"].update(player_first_name="private"),
        lambda item: item["entry"].update(started_event=0),
        lambda item: item["history"].update(past=[]),
        lambda item: item["history"]["current"][0].update(points=50),
        lambda item: item["history"]["current"][0].update(event_transfers_cost=-4),
        lambda item: item["transfers"][0].update(element_in_cost=None),
        lambda item: item["picks"][0]["entry_history"].update(points=61),
        lambda item: item["picks"][0]["picks"][0].update(selling_price=55),
        lambda item: item["picks"][0]["picks"][0].update(is_captain=1),
        lambda item: item["current_week"].update(active_chip="manager"),
        lambda item: item["current_week"]["pick_order"].pop(),
        lambda item: item.pop("current_week"),
    ],
)
def test_bundle_schema_refuses_malformed_or_unrequested_values(damage):
    example = copy.deepcopy(BUNDLE_EXAMPLES["late_joiner"])
    damage(example)
    with pytest.raises(ValidationError):
        _validator(BUNDLE).validate(example)


def test_bundle_without_a_member_week_is_still_a_bundle():
    example = copy.deepcopy(BUNDLE_EXAMPLES["late_joiner"])
    example["current_week"] = None
    _validator(BUNDLE).validate(example)

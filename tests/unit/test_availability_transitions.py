"""The transitions count reads two decision captures and says only what they say.

Synthetic captures: a gameweek with two captures (the later one is the decision capture),
the next gameweek with one, and no capture for the week after. Players stated at 25, 50
and 75 resolve every way the rule names, one is no longer listed, one carries a status the
rule does not know, and two are outside the population. No note text reaches the record.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from scripts.measure_availability_transitions import (
    OUTCOME_CLASSES,
    STATED_CHANCES,
    decision_captures,
    measure,
    pair_transitions,
    resolve,
    run,
    summary,
    wilson_interval,
)

from squadopt.data.snapshots import write_snapshot
from squadopt.data.sources import BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD

EVENTS = [
    {"id": 6, "deadline_time": "2026-10-10T10:00:00Z", "finished": False},
    {"id": 7, "deadline_time": "2026-10-17T17:30:00Z", "finished": False},
    {"id": 8, "deadline_time": "2026-10-24T13:30:00Z", "finished": False},
]
TEAMS = [{"id": 1, "code": 3, "name": "Club 1", "short_name": "C1"}]


def _element(code: int, status: str, chance: int | None, news: str = "") -> dict[str, Any]:
    return {
        "code": code,
        "id": code,
        "first_name": "Player",
        "second_name": str(code),
        "team": 1,
        "element_type": 3,
        "now_cost": 50,
        "status": status,
        "chance_of_playing_next_round": chance,
        "news": news,
        "news_added": "2026-10-08T09:00:00Z" if news else None,
    }


# Stated at the GW6 decision: how each stands at the GW7 decision.
EARLIER = [
    _element(1, "d", 75, "Hamstring injury - 75% chance of playing"),
    _element(2, "d", 50, "Knock - 50% chance of playing"),
    _element(3, "d", 25, "Illness - 25% chance of playing"),
    _element(4, "a", 75),
    _element(5, "d", 50),
    _element(6, "i", 0, "Knee injury - Expected back 7 Nov"),
    _element(7, "a", 100),
    _element(8, "d", 25),
    _element(9, "a", None),
]
LATER = [
    _element(1, "a", None),  # available, by status
    _element(2, "d", 50),  # still doubtful
    _element(3, "i", 0, "Illness - Expected back 24 Oct"),  # out, by chance
    # 4 is no longer listed: absent
    _element(5, "x", None),  # a status the rule does not know
    _element(6, "i", 0),
    _element(7, "a", 100),
    _element(8, "d", 100),  # available: the stated chance wins over the status
    _element(9, "a", None),
]


def _bootstrap(elements: list[dict[str, Any]]) -> bytes:
    return json.dumps({"events": EVENTS, "teams": TEAMS, "elements": elements}).encode()


def _write(root: Path, captured_at: str, elements: list[dict[str, Any]]) -> str:
    return write_snapshot(
        root,
        source="fpl-live",
        captured_at_utc=captured_at,
        payloads={BOOTSTRAP_PAYLOAD: _bootstrap(elements), FIXTURES_PAYLOAD: b"[]"},
    ).snapshot_id


@pytest.fixture
def captures(tmp_path: Path) -> Path:
    root = tmp_path / "snapshots"
    _write(root, "2026-10-09T08:00:00Z", [_element(1, "a", None)])  # an earlier GW6 capture
    _write(root, "2026-10-10T07:00:00Z", EARLIER)  # the GW6 decision capture
    _write(root, "2026-10-16T12:00:00Z", LATER)  # the GW7 decision capture; nothing for GW8
    return root


def test_the_decision_capture_is_the_latest_one_whose_open_deadline_is_that_week(captures):
    chosen = decision_captures(captures)
    assert sorted(chosen) == [6, 7]
    assert chosen[6].captured_at_utc == "2026-10-10T07:00:00Z"
    assert chosen[6].deadline_utc == "2026-10-10T10:00:00Z"
    assert chosen[7].deadline_utc == "2026-10-17T17:30:00Z"


@pytest.mark.parametrize(
    ("status", "chance", "expected"),
    [
        ("d", 100, "available"),
        ("a", 0, "out"),
        ("a", 75, "doubtful"),
        ("d", 40, "unknown"),
        ("a", None, "available"),
        ("d", None, "doubtful"),
        ("i", None, "out"),
        ("s", None, "out"),
        ("u", None, "out"),
        ("n", None, "out"),
        ("x", None, "unknown"),
    ],
)
def test_the_later_row_is_read_by_the_availability_rules_precedence(status, chance, expected):
    assert resolve(status, chance) == expected


def test_a_pair_counts_every_stated_player_once_and_names_what_happened(captures):
    chosen = decision_captures(captures)
    pair = pair_transitions(chosen[6], chosen[7])
    by_chance = {cell["stated_chance"]: cell for cell in pair["cells"]}
    assert set(by_chance) == {25, 50, 75, None}
    assert by_chance[75]["players"] == {
        "available": [1],
        "doubtful": [],
        "out": [],
        "absent": [4],
        "unknown": [],
    }
    assert by_chance[50]["counts"] == {
        "available": 0,
        "doubtful": 1,
        "out": 0,
        "absent": 0,
        "unknown": 1,
    }
    assert by_chance[25]["players"]["out"] == [3] and by_chance[25]["players"]["available"] == [8]
    pooled = by_chance[None]
    assert pooled["players_stated"] == 6
    assert sum(pooled["counts"].values()) == 6
    assert set(pooled["counts"]) == set(OUTCOME_CLASSES)
    # Stated 0, 100 and nothing are outside the population.
    everyone = {code for codes in pooled["players"].values() for code in codes}
    assert everyone == {1, 2, 3, 4, 5, 8}
    assert by_chance[75]["shares"]["available"]["value"] == 0.5
    assert by_chance[75]["shares"]["available"]["wilson_90"] == pytest.approx(
        list(wilson_interval(1, 2))
    )


def test_wilson_interval_is_the_score_interval_and_absent_for_no_trials():
    assert wilson_interval(0, 0) is None
    # Hand values: p = 0.5, n = 2, z = 1.6449; centre 0.5, half-width 0.3792.
    low, high = wilson_interval(1, 2)
    assert low == pytest.approx(0.1208, abs=1e-4) and high == pytest.approx(0.8792, abs=1e-4)
    assert wilson_interval(2, 2) == pytest.approx((0.4250, 1.0), abs=1e-4)
    assert wilson_interval(0, 10)[0] == 0.0
    with pytest.raises(ValueError, match="between"):
        wilson_interval(3, 2)


def test_a_pair_must_be_consecutive_and_the_later_capture_after_the_earlier_deadline(captures):
    chosen = decision_captures(captures)
    with pytest.raises(ValueError, match="consecutive"):
        pair_transitions(chosen[7], chosen[6])


def test_prospective_means_the_earlier_deadline_fell_after_the_protocol_merged(captures):
    before = measure(captures, "2026-10-09T12:00:00Z")
    after = measure(captures, "2026-10-11T00:00:00Z")
    assert [pair["prospective"] for pair in before["pairs"]] == [True]
    assert [pair["prospective"] for pair in after["pairs"]] == [False]
    assert before["prospective_pairs"] == 1 and after["prospective_pairs"] == 0
    assert before["gameweeks_without_partner"] == [7]
    assert before["captures_read"] == 3 and len(before["decision_captures"]) == 2


def test_no_note_text_leaves_the_capture_and_the_record_says_so(captures, tmp_path):
    record = run(captures, "2026-10-09T12:00:00Z", tmp_path / "out")
    text = (tmp_path / "out" / "record.json").read_text()
    for word in ("Hamstring", "Knock", "Illness", "Expected back", '"news"', "news_added"):
        assert word not in text
    assert record["news_text_included"] is False and record["outcomes_read"] is False
    assert record["measurement_only"] is True and record["gate_evidence"] is False
    assert record["locked_holdout_accessed"] is False
    assert record["stated_chances"] == list(STATED_CHANCES)
    with pytest.raises(FileExistsError):
        run(captures, "2026-10-09T12:00:00Z", tmp_path / "out")


def test_the_summary_prints_counts_and_the_interval_and_names_the_week_without_a_pair(captures):
    text = summary(measure(captures, "2026-10-09T12:00:00Z"))
    assert "| GW6 to GW7 | yes | 75 | 2 | 1 | 0 | 0 | 1 | 0 | 0.50 [0.12, 0.88] |" in text
    assert "| GW6 to GW7 | yes | all | 6 |" in text
    assert "No pair for gameweek(s) 7." in text
    assert "No share is a calibrated probability" in text

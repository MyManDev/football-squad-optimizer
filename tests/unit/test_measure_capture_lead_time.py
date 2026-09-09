"""Tests for the capture lead-time measurement.

Every capture here is written by the test from hand-built payloads. Nothing reaches a
network and no real captured bytes are read, which is also the only way this can run in
CI: `data/snapshots/` is gitignored, so the artifact this script writes is produced on the
machine that holds the captures, never here.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from scripts.measure_capture_lead_time import (
    BUCKETS,
    LeadTimeMeasurementError,
    classify,
    measure,
)

from squadopt.data.snapshots import write_snapshot
from squadopt.data.sources import BOOTSTRAP_PAYLOAD, FPL_LIVE_SOURCE

DEADLINE = "2026-09-12T17:30:00Z"
NEXT_DEADLINE = "2026-09-18T17:30:00Z"

# Thirty hours before the deadline, and then two and a half: the two lead times the
# measurement exists to compare.
EARLY = "2026-09-11T11:30:00Z"
LATE = "2026-09-12T15:00:00Z"


def _element(code: int, **overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "code": code,
        "id": code,
        "first_name": "Given",
        "second_name": "Name",
        "team": 1,
        "element_type": 3,
        "now_cost": 55,
        "status": "a",
        "chance_of_playing_next_round": 100,
        "news": "",
        "news_added": None,
    }
    record.update(overrides)
    return record


def _bootstrap(
    elements: list[dict[str, Any]] | None = None,
    *,
    deadline: str = DEADLINE,
    gameweek: int = 4,
) -> bytes:
    document = {
        "teams": [{"id": 1, "code": 3, "name": "Arsenal", "short_name": "ARS"}],
        "elements": [_element(1)] if elements is None else elements,
        "events": [
            {"id": gameweek - 1, "deadline_time": "2026-09-05T17:30:00Z", "finished": True},
            {"id": gameweek, "deadline_time": deadline, "finished": False},
            {"id": gameweek + 1, "deadline_time": NEXT_DEADLINE, "finished": False},
        ],
    }
    return json.dumps(document).encode("utf-8")


def _capture(
    root: Path,
    captured_at_utc: str,
    bootstrap: bytes,
    *,
    source: str = FPL_LIVE_SOURCE,
    payload_name: str = BOOTSTRAP_PAYLOAD,
) -> str:
    metadata = write_snapshot(
        root,
        source=source,
        captured_at_utc=captured_at_utc,
        payloads={payload_name: bootstrap},
    )
    return metadata.snapshot_id


# --- the classifier ---------------------------------------------------------
#
# It is a keyword rule and the tests say so: what is asserted is which bucket the rule
# picks, never what the note "really" was.


@pytest.mark.parametrize(
    ("news", "expected"),
    [
        ("Knee injury - expected back in October", "fitness_or_suspension"),
        ("Suspended for three matches", "fitness_or_suspension"),
        ("Hamstring strain", "fitness_or_suspension"),
        ("Has joined Real Madrid", "transfer"),
        ("Season-long loan to Ipswich", "transfer"),
        ("Left the club by mutual consent", "transfer"),
    ],
)
def test_the_declared_vocabulary_decides_the_bucket(news: str, expected: str) -> None:
    assert classify(news, "a") == expected


def test_a_transfer_note_mentioning_fitness_is_a_transfer() -> None:
    """The precedence is declared, so a note carrying both words lands predictably."""

    assert classify("Joined on loan while recovering from a knock", "a") == "transfer"


def test_a_note_the_rule_does_not_recognise_is_not_forced_into_a_bucket() -> None:
    assert classify("Awaiting international clearance", "a") == "unclassified"


def test_an_empty_note_is_unclassified_not_a_transfer() -> None:
    """A cleared flag leaves an empty note behind; it is not evidence of anything."""

    assert classify("", "a") == "unclassified"


def test_a_suspended_status_classifies_a_note_the_words_did_not() -> None:
    assert classify("Unavailable", "s") == "fitness_or_suspension"


def test_an_unavailable_status_is_never_read_as_a_transfer() -> None:
    """The payload never says *why* a player is unavailable, so nothing is inferred."""

    assert classify("Unavailable", "u") == "unclassified"


# --- the window -------------------------------------------------------------


def test_the_window_holds_what_the_earlier_capture_could_not(tmp_path: Path) -> None:
    inside = _element(2, news="Knee injury", news_added="2026-09-12T09:00:00Z", status="i")
    before = _element(3, news="Ankle knock", news_added="2026-09-01T09:00:00Z", status="d")
    _capture(tmp_path, EARLY, _bootstrap([_element(1), before]))
    _capture(tmp_path, LATE, _bootstrap([_element(1), before, inside]))

    record = measure(tmp_path)

    (gameweek,) = list(record["gameweeks"])
    recovered = gameweek["recovered"]
    assert recovered["items_recovered"] == 1
    assert recovered["players_by_bucket"]["fitness_or_suspension"] == [2]
    assert recovered["window_hours"] == 27.5


def test_the_window_is_open_at_its_start_and_closed_at_its_end(tmp_path: Path) -> None:
    """A note stamped at the earlier capture's own instant was already in it."""

    at_open = _element(2, news="Knee injury", news_added=EARLY)
    at_close = _element(3, news="Knee injury", news_added=LATE)
    _capture(tmp_path, EARLY, _bootstrap([_element(1)]))
    _capture(tmp_path, LATE, _bootstrap([_element(1), at_open, at_close]))

    record = measure(tmp_path)

    (gameweek,) = list(record["gameweeks"])
    assert gameweek["recovered"]["players_by_bucket"]["fitness_or_suspension"] == [3]


def test_the_three_buckets_stay_apart(tmp_path: Path) -> None:
    """Nothing is folded: an unclassified item is its own number, not a transfer."""

    added = "2026-09-12T09:00:00Z"
    _capture(tmp_path, EARLY, _bootstrap([_element(1)]))
    _capture(
        tmp_path,
        LATE,
        _bootstrap(
            [
                _element(1),
                _element(2, news="Hamstring injury", news_added=added, status="i"),
                _element(3, news="Has joined Napoli", news_added=added, status="u"),
                _element(4, news="Awaiting clearance", news_added=added, status="u"),
            ]
        ),
    )

    record = measure(tmp_path)

    (gameweek,) = list(record["gameweeks"])
    counts = gameweek["recovered"]["items_by_bucket"]
    assert counts == {"fitness_or_suspension": 1, "transfer": 1, "unclassified": 1}
    assert set(counts) == set(BUCKETS)


def test_a_lead_time_is_the_hours_the_payload_itself_published(tmp_path: Path) -> None:
    _capture(tmp_path, EARLY, _bootstrap())
    _capture(tmp_path, LATE, _bootstrap())

    record = measure(tmp_path)

    (gameweek,) = list(record["gameweeks"])
    assert gameweek["earliest_lead_time_hours"] == 30.0
    assert gameweek["latest_lead_time_hours"] == 2.5
    assert gameweek["deadline_utc"] == DEADLINE


def test_gameweeks_are_reported_separately(tmp_path: Path) -> None:
    _capture(tmp_path, EARLY, _bootstrap(gameweek=4))
    _capture(tmp_path, LATE, _bootstrap(gameweek=4))
    _capture(tmp_path, "2026-09-17T11:30:00Z", _bootstrap(deadline=DEADLINE, gameweek=4))

    record = measure(tmp_path)

    assert [entry["gameweek"] for entry in list(record["gameweeks"])] == [4, 5]


# --- what is not measured ---------------------------------------------------


def test_one_capture_is_not_a_zero(tmp_path: Path) -> None:
    """The whole point of the artifact: absent and zero are different claims."""

    _capture(tmp_path, EARLY, _bootstrap())

    record = measure(tmp_path)

    (gameweek,) = list(record["gameweeks"])
    assert gameweek["recovered"] is None
    assert gameweek["recovered_unavailable_reason"] == "one_capture"
    assert record["gameweeks_measured"] == 0
    assert record["gameweeks_seen"] == 1


def test_a_capture_carrying_no_bootstrap_is_skipped_not_fatal(tmp_path: Path) -> None:
    """What an interrupted capture leaves behind must not stop the others."""

    _capture(tmp_path, EARLY, _bootstrap())
    _capture(tmp_path, LATE, _bootstrap())
    _capture(tmp_path, "2026-09-12T15:30:00Z", b"{}", payload_name="fixtures.json")

    record = measure(tmp_path)

    assert record["captures_read"] == 2
    assert record["gameweeks_measured"] == 1


def test_a_capture_past_every_deadline_describes_no_open_gameweek(tmp_path: Path) -> None:
    _capture(tmp_path, EARLY, _bootstrap())
    _capture(tmp_path, LATE, _bootstrap())
    _capture(tmp_path, "2026-10-01T09:00:00Z", _bootstrap())

    record = measure(tmp_path)

    assert record["captures_read"] == 2


def test_another_source_sharing_the_root_is_not_walked(tmp_path: Path) -> None:
    _capture(tmp_path, EARLY, _bootstrap())
    _capture(tmp_path, LATE, _bootstrap())
    _capture(tmp_path, LATE, _bootstrap(), source="fpl-top100")

    record = measure(tmp_path)

    assert record["captures_read"] == 2


def test_an_empty_root_measures_nothing_rather_than_claiming_zero(tmp_path: Path) -> None:
    record = measure(tmp_path)

    assert record["gameweeks_seen"] == 0
    assert record["gameweeks"] == []


# --- refusals ---------------------------------------------------------------


def test_a_moved_deadline_is_refused_rather_than_measured(tmp_path: Path) -> None:
    """Two captures of "gameweek 4" against different deadlines are two different weeks."""

    _capture(tmp_path, EARLY, _bootstrap())
    _capture(tmp_path, LATE, _bootstrap(deadline="2026-09-12T18:00:00Z"))

    with pytest.raises(LeadTimeMeasurementError, match="moved deadline"):
        measure(tmp_path)


def test_two_captures_inside_one_second_measure_no_window(tmp_path: Path) -> None:
    """The ids differ because the payloads do, so the pair reaches the window check."""

    _capture(tmp_path, EARLY, _bootstrap([_element(1)]))
    _capture(tmp_path, EARLY, _bootstrap([_element(1), _element(2)]))

    with pytest.raises(LeadTimeMeasurementError, match="measure no"):
        measure(tmp_path)


# --- the record itself ------------------------------------------------------


def test_the_record_says_what_it_is_not(tmp_path: Path) -> None:
    _capture(tmp_path, EARLY, _bootstrap())
    _capture(tmp_path, LATE, _bootstrap())

    record = measure(tmp_path)

    assert record["gate_evidence"] is False
    assert record["measurement_only"] is True
    assert record["locked_holdout_accessed"] is False
    assert record["contract_version"] == "capture_lead_time_v1"
    assert record["news_classifier_version"] == "news_keywords_v1"


def test_the_record_carries_no_word_of_the_notes(tmp_path: Path) -> None:
    """Ids are auditable against the local capture; the source's text is not copied out."""

    _capture(tmp_path, EARLY, _bootstrap([_element(1)]))
    _capture(
        tmp_path,
        LATE,
        _bootstrap(
            [_element(1), _element(2, news="Knee injury", news_added="2026-09-12T09:00:00Z")]
        ),
    )

    record = measure(tmp_path)

    assert "Knee injury" not in json.dumps(record)

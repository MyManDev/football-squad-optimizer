"""Tests for the feed-freshness measurement (#1109).

Every capture is written by the test from hand-built payloads, through the same helpers as
the lead-time runner's tests; nothing reaches a network and no real captured bytes are read.
"""

import json
from pathlib import Path

import pytest
from scripts.measure_feed_freshness import (
    FEED_FRESHNESS_CONTRACT_VERSION,
    QUANTILE_METHOD,
    main,
    measure,
    summary,
)
from tests.unit.test_measure_capture_lead_time import _bootstrap, _capture, _element

# The bootstrap helper publishes GW3 at 2026-09-05T17:30Z, GW4 at 2026-09-12T17:30Z and GW5
# at 2026-09-18T17:30Z, so a capture on 2026-09-11 has 2026-09-05T17:30Z as its previous
# deadline.
CAPTURED = "2026-09-11T12:00:00Z"
PREVIOUS = "2026-09-05T17:30:00Z"


def _note(code: int, news: str, added: str | None) -> dict[str, object]:
    return _element(code, news=news, news_added=added)


def _single(tmp_path: Path, elements: list[dict[str, object]], captured: str = CAPTURED):
    _capture(tmp_path, captured, _bootstrap(elements))
    record = measure(tmp_path)
    assert record["captures_read"] == 1
    return record["captures"][0]


def test_ages_are_days_from_each_stamp_to_the_capture_with_linear_quartiles(
    tmp_path: Path,
) -> None:
    # Ages of 1, 2, 4 and 10 days: median 3.0, first quartile 1.75, third 5.5 (linear).
    elements = [
        _note(1, "Knee injury", "2026-09-10T12:00:00Z"),
        _note(2, "Ill", "2026-09-09T12:00:00Z"),
        _note(3, "Suspended", "2026-09-07T12:00:00Z"),
        _note(4, "Hamstring", "2026-09-01T12:00:00Z"),
    ]
    entry = _single(tmp_path, elements)
    assert entry["notes"] == 4
    assert entry["age"] == {"q1_days": 1.75, "median_days": 3.0, "q3_days": 5.5}
    assert entry["previous_deadline_utc"] == PREVIOUS
    # Stamped after 2026-09-05T17:30Z: the first three.
    assert entry["notes_since_previous_deadline"] == 3
    assert entry["notes_since_previous_deadline_unavailable_reason"] is None


def test_a_player_without_a_note_is_not_an_age_of_zero(tmp_path: Path) -> None:
    elements = [
        _note(1, "Knee injury", "2026-09-01T12:00:00Z"),
        _element(2),
        _element(3),
    ]
    entry = _single(tmp_path, elements)
    assert entry["notes"] == 1
    assert entry["age"] == {"q1_days": 10.0, "median_days": 10.0, "q3_days": 10.0}
    assert entry["players_without_note"] == 2


def test_a_cleared_flag_an_unstamped_note_and_a_later_stamp_enter_no_age(tmp_path: Path) -> None:
    elements = [
        _note(1, "Knee injury", "2026-09-09T12:00:00Z"),
        _note(2, "", "2026-09-10T12:00:00Z"),
        _note(3, "Doubtful", None),
        _note(4, "Hamstring", "2026-09-11T13:00:00Z"),
    ]
    entry = _single(tmp_path, elements)
    assert entry["notes"] == 1
    assert entry["age"]["median_days"] == 2.0
    assert entry["cleared_flags"] == 1
    assert entry["notes_without_stamp"] == 1
    assert entry["stamps_after_capture"] == 1
    assert entry["notes_since_previous_deadline"] == 1


def test_a_note_stamped_exactly_at_the_previous_deadline_is_not_since_it(tmp_path: Path) -> None:
    elements = [
        _note(1, "Knee injury", PREVIOUS),
        _note(2, "Ill", "2026-09-05T17:30:01Z"),
    ]
    entry = _single(tmp_path, elements)
    assert entry["notes_since_previous_deadline"] == 1


def test_a_capture_before_the_first_deadline_has_no_since_count_not_zero(
    tmp_path: Path,
) -> None:
    elements = [_note(1, "Knee injury", "2026-09-01T12:00:00Z")]
    entry = _single(tmp_path, elements, captured="2026-09-04T12:00:00Z")
    assert entry["previous_deadline_utc"] is None
    assert entry["notes_since_previous_deadline"] is None
    assert entry["notes_since_previous_deadline_unavailable_reason"] == "no_previous_deadline"
    assert "not measured" in summary(measure(tmp_path))


def test_a_capture_with_no_note_has_no_age(tmp_path: Path) -> None:
    entry = _single(tmp_path, [_element(1), _element(2)])
    assert entry["notes"] == 0
    assert entry["age"] is None
    assert entry["notes_since_previous_deadline"] == 0
    assert "no note" in summary(measure(tmp_path))


def test_each_capture_is_its_own_row_in_capture_order(tmp_path: Path) -> None:
    late = _capture(
        tmp_path,
        "2026-09-12T15:00:00Z",
        _bootstrap([_note(1, "Knee injury", "2026-09-12T12:00:00Z")]),
    )
    early = _capture(
        tmp_path, CAPTURED, _bootstrap([_note(1, "Knee injury", "2026-09-10T12:00:00Z")])
    )
    record = measure(tmp_path)
    assert [entry["snapshot_id"] for entry in record["captures"]] == [early, late]
    assert [entry["age"]["median_days"] for entry in record["captures"]] == [1.0, 0.12]


def test_the_record_declares_its_contract_and_reads_no_holdout(tmp_path: Path) -> None:
    _capture(tmp_path, CAPTURED, _bootstrap([_note(1, "Knee injury", "2026-09-10T12:00:00Z")]))
    record = measure(tmp_path)
    assert record["contract_version"] == FEED_FRESHNESS_CONTRACT_VERSION == "feed_freshness_v1"
    assert record["quantile_method"] == QUANTILE_METHOD == "linear"
    assert record["note_rule"] == "nonempty_news_with_news_added_v1"
    assert record["measurement_only"] is True and record["gate_evidence"] is False
    assert record["locked_holdout_accessed"] is False
    # The notes' words are never written.
    assert "Knee" not in json.dumps(record) and "Knee" not in summary(record)


def test_the_command_writes_both_files_and_refuses_an_empty_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "snapshots"
    root.mkdir()
    out_json, out_md = tmp_path / "out.json", tmp_path / "out.md"
    arguments = ["--snapshot-root", str(root), "--json-output", str(out_json)]
    arguments += ["--markdown-output", str(out_md)]
    assert main(arguments) == 1
    assert not out_json.exists()
    _capture(root, CAPTURED, _bootstrap([_note(1, "Knee injury", "2026-09-10T12:00:00Z")]))
    assert main(arguments) == 0
    assert json.loads(out_json.read_text(encoding="utf-8"))["captures_read"] == 1
    assert out_md.read_text(encoding="utf-8").startswith("# How old the feed's notes are")
    assert "1 note(s), median 1.0 d, 1 since the previous deadline" in capsys.readouterr().out


def test_a_deadline_at_the_capture_instant_is_the_previous_deadline(tmp_path: Path) -> None:
    elements = [_note(1, "Knee injury", "2026-09-05T12:00:00Z")]
    entry = _single(tmp_path, elements, captured=PREVIOUS)
    assert entry["previous_deadline_utc"] == PREVIOUS
    assert entry["notes_since_previous_deadline"] == 0

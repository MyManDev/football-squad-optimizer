"""The transitions count reads consecutive decision captures and says only what they say.

Synthetic captures: a gameweek with two captures (the later one is the decision capture),
two following gameweeks with one each, a capture with no bootstrap and one taken after
every deadline (both skipped, with their reason), and nothing for the week after. Players
stated at 25, 50 and 75 resolve every way the rule names, one is no longer listed, one
carries a status the rule does not know, and three are outside the population. No note text
reaches the record, a refusal leaves no directory behind, and pooling takes prospective
pairs only.
"""

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from scripts.measure_availability_transitions import (
    OUTCOME_CLASSES,
    REPOSITORY_ROOT,
    STATED_CHANCES,
    TransitionsRefusal,
    decision_captures,
    main,
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
GW6 = [
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
GW7 = [
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
GW8 = [_element(2, "a", None), *(_element(code, "a", None) for code in (1, 3, 5, 6, 7, 8, 9))]


def _bootstrap(elements: list[dict[str, Any]]) -> bytes:
    return json.dumps({"events": EVENTS, "teams": TEAMS, "elements": elements}).encode()


def _write(root: Path, captured_at: str, elements: list[dict[str, Any]] | None) -> str:
    payloads = {FIXTURES_PAYLOAD: b"[]"}
    if elements is not None:
        payloads[BOOTSTRAP_PAYLOAD] = _bootstrap(elements)
    return write_snapshot(
        root, source="fpl-live", captured_at_utc=captured_at, payloads=payloads
    ).snapshot_id


@pytest.fixture
def captures(tmp_path: Path) -> Path:
    root = tmp_path / "snapshots"
    _write(root, "2026-10-09T08:00:00Z", [_element(1, "a", None)])  # an earlier GW6 capture
    _write(root, "2026-10-10T07:00:00Z", GW6)  # the GW6 decision capture
    _write(root, "2026-10-16T12:00:00Z", GW7)  # the GW7 decision capture
    _write(root, "2026-10-24T09:00:00Z", GW8)  # the GW8 decision capture; nothing for GW9
    _write(root, "2026-10-11T00:00:00Z", None)  # no bootstrap: skipped
    _write(root, "2026-10-25T00:00:00Z", GW8)  # after every deadline: skipped
    return root


def test_the_decision_capture_is_the_latest_one_whose_open_deadline_is_that_week(
    captures: Path,
) -> None:
    chosen, skipped = decision_captures(captures)
    assert sorted(chosen) == [6, 7, 8]
    assert chosen[6].captured_at_utc == "2026-10-10T07:00:00Z"
    assert chosen[6].deadline_utc == "2026-10-10T10:00:00Z"
    assert chosen[7].deadline_utc == "2026-10-17T17:30:00Z"
    assert sorted(s["reason"] for s in skipped) == ["after_every_deadline", "no_bootstrap_payload"]
    assert all(s["snapshot_id"].startswith("fpl-live-") for s in skipped)


def test_a_missing_root_or_one_without_live_captures_is_refused(tmp_path: Path) -> None:
    with pytest.raises(TransitionsRefusal, match="No snapshot directory"):
        decision_captures(tmp_path / "nowhere")
    (tmp_path / "empty").mkdir()
    with pytest.raises(TransitionsRefusal, match="No fpl-live captures"):
        decision_captures(tmp_path / "empty")


@pytest.mark.parametrize(
    ("status", "chance", "expected"),
    [
        ("d", 100, "available"),
        ("a", 0, "out"),
        ("a", 75, "doubtful"),
        ("d", 40, "doubtful"),
        ("a", 0.5, "doubtful"),
        ("a", 101, "unknown"),
        ("a", float("nan"), "unknown"),
        ("x", 50, "unknown"),
        ("a", None, "available"),
        ("d", None, "doubtful"),
        ("i", None, "out"),
        ("s", None, "out"),
        ("u", None, "out"),
        ("n", None, "out"),
        ("x", None, "unknown"),
    ],
)
def test_the_later_row_is_read_by_the_availability_rules_precedence(
    status: str, chance: float | None, expected: str
) -> None:
    assert resolve(status, chance) == expected


def test_a_pair_counts_every_stated_player_once_and_names_what_happened(captures: Path) -> None:
    chosen, _ = decision_captures(captures)
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
    assert pooled["players_stated"] == 6 and sum(pooled["counts"].values()) == 6
    assert set(pooled["counts"]) == set(OUTCOME_CLASSES)
    # Stated 0, 100 and nothing are outside the population.
    assert {code for codes in pooled["players"].values() for code in codes} == {1, 2, 3, 4, 5, 8}
    assert by_chance[75]["shares"]["available"]["value"] == 0.5
    assert by_chance[75]["shares"]["available"]["wilson_90"] == pytest.approx(
        list(wilson_interval(1, 2))
    )
    # Among the resolved: 75 has one available and none out; 25 has one of each; 50 none.
    assert by_chance[75]["available_among_resolved"]["value"] == 1.0
    assert by_chance[25]["available_among_resolved"]["value"] == 0.5
    assert by_chance[50]["available_among_resolved"] is None
    assert all(cell["small_sample"] and cell["small_resolved"] for cell in pair["cells"])
    assert pooled["distinct_players"] == 6


def test_wilson_interval_is_the_score_interval_and_absent_for_no_trials() -> None:
    assert wilson_interval(0, 0) is None
    # Hand values: p = 0.5, n = 2, z = 1.6449; centre 0.5, half-width 0.3792.
    low, high = wilson_interval(1, 2)
    assert low == pytest.approx(0.1208, abs=1e-4) and high == pytest.approx(0.8792, abs=1e-4)
    assert wilson_interval(2, 2) == pytest.approx((0.4250, 1.0), abs=1e-4)
    assert wilson_interval(0, 10)[0] == 0.0
    with pytest.raises(ValueError, match="between"):
        wilson_interval(3, 2)


def test_a_pair_is_consecutive_follows_the_earlier_deadline_and_repeats_no_player(
    captures: Path,
) -> None:
    chosen, _ = decision_captures(captures)
    with pytest.raises(TransitionsRefusal, match="consecutive"):
        pair_transitions(chosen[7], chosen[6])
    early = replace(chosen[7], captured_at_utc="2026-10-10T09:00:00Z")
    with pytest.raises(TransitionsRefusal, match="follow the earlier deadline"):
        pair_transitions(chosen[6], early)
    moved = [dict(e, deadline_time="2026-10-12T10:00:00Z") if e["id"] == 6 else e for e in EVENTS]
    republished = replace(
        chosen[7],
        bootstrap=json.dumps({"events": moved, "teams": TEAMS, "elements": GW7}).encode(),
    )
    with pytest.raises(TransitionsRefusal, match="different deadline"):
        pair_transitions(chosen[6], republished)
    repeated = replace(chosen[6], bootstrap=_bootstrap([*GW6, _element(1, "d", 75)]))
    with pytest.raises(TransitionsRefusal, match="repeats a player"):
        pair_transitions(repeated, chosen[7])


def test_prospective_means_the_earlier_deadline_fell_after_the_protocol_merged(
    captures: Path,
) -> None:
    both = measure(captures, "2026-10-09T15:00:00+03:00", protocol_commit="abc1234")
    assert both["protocol_merged_at_utc"] == "2026-10-09T12:00:00Z"
    assert [pair["prospective"] for pair in both["pairs"]] == [True, True]
    assert both["prospective_pairs"] == 2 and both["pooled_prospective"]["pairs"] == 2
    assert both["protocol_commit"] == "abc1234"
    # Player 2 is doubtful at GW6 and at GW7: two observations of one player.
    pooled_all = next(c for c in both["pooled_prospective"]["cells"] if c["stated_chance"] is None)
    assert pooled_all["players_stated"] == 7 and pooled_all["distinct_players"] == 6
    assert both["gameweeks_without_partner"] == [8]
    assert both["captures_read"] == 6 and len(both["decision_captures"]) == 3
    assert len(both["captures_skipped"]) == 2
    later = measure(captures, "2026-10-12T00:00:00Z")
    assert [pair["prospective"] for pair in later["pairs"]] == [False, True]
    pooled = {cell["stated_chance"]: cell for cell in later["pooled_prospective"]["cells"]}
    # Only GW7 to GW8 is pooled: one player stated 50 at GW7, available at GW8.
    assert later["pooled_prospective"]["pairs"] == 1
    assert pooled[50]["counts"]["available"] == 1 and pooled[50]["players_stated"] == 1
    assert pooled[75]["players_stated"] == 0 and pooled[75]["shares"] is None
    assert pooled[None]["players_stated"] == 1
    bounded = measure(captures, "2026-10-09T12:00:00Z", through_gameweek=7)
    assert [pair["later"]["gameweek"] for pair in bounded["pairs"]] == [7]
    assert bounded["through_gameweek"] == 7
    # The reading's inventory ends at its bound: GW8 is not part of it, GW7 has no partner.
    assert [d["gameweek"] for d in bounded["decision_captures"]] == [6, 7]
    assert bounded["gameweeks_without_partner"] == [7]
    with pytest.raises(TransitionsRefusal, match=r"1\.\.38"):
        measure(captures, "2026-10-09T12:00:00Z", through_gameweek=40)
    with pytest.raises(TransitionsRefusal, match="No decision capture at or before"):
        measure(captures, "2026-10-09T12:00:00Z", through_gameweek=3)
    with pytest.raises(TransitionsRefusal, match="offset"):
        measure(captures, "2026-10-09T12:00:00")


def test_no_note_text_leaves_the_capture_and_the_record_says_so(
    captures: Path, tmp_path: Path
) -> None:
    record = run(captures, "2026-10-09T12:00:00Z", tmp_path / "out")
    text = (tmp_path / "out" / "record.json").read_text()
    for word in ("Hamstring", "Knock", "Illness", "Expected back", '"news"', "news_added"):
        assert word not in text
    assert record["news_text_included"] is False and record["outcomes_read"] is False
    assert record["measurement_only"] is True and record["gate_evidence"] is False
    assert record["locked_holdout_accessed"] is False
    assert record["stated_chances"] == list(STATED_CHANCES)
    assert record["classification"] == "availability_transitions_classes_v1"
    assert record["precedence_from"] == "captured_availability_rule_v1"
    with pytest.raises(FileExistsError):
        run(captures, "2026-10-09T12:00:00Z", tmp_path / "out")


def test_a_refusal_leaves_no_directory_and_the_inputs_are_never_written_into(
    captures: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(TransitionsRefusal, match="inside the snapshot root"):
        run(captures, "2026-10-09T12:00:00Z", captures / "out")
    with pytest.raises(TransitionsRefusal, match="ISO-8601"):
        run(captures, "not an instant", tmp_path / "refused")
    assert not (tmp_path / "refused").exists()
    # The repository's data/ and docs/ are refused from any working directory.
    monkeypatch.chdir(tmp_path)
    for name in ("data", "docs"):
        with pytest.raises(TransitionsRefusal, match=f"repository's {name}/"):
            run(captures, "2026-10-09T12:00:00Z", REPOSITORY_ROOT / name / "transitions_probe")
        assert not (REPOSITORY_ROOT / name / "transitions_probe").exists()
    (tmp_path / "afile").write_text("x")
    with pytest.raises(TransitionsRefusal, match="under a file"):
        run(captures, "2026-10-09T12:00:00Z", tmp_path / "afile" / "child")


def test_main_refuses_on_stderr_and_reports_on_stdout(
    captures: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        [
            "--snapshot-root",
            str(tmp_path / "nowhere"),
            "--protocol-merged-at",
            "2026-10-09T12:00:00Z",
            "--protocol-commit",
            "abc1234",
            "--output",
            str(tmp_path / "a"),
        ]
    )
    assert code == 1 and "Refused: No snapshot directory" in capsys.readouterr().err
    assert not (tmp_path / "a").exists()
    code = main(
        [
            "--snapshot-root",
            str(captures),
            "--protocol-merged-at",
            "2026-10-12T00:00:00Z",
            "--protocol-commit",
            "abc1234",
            "--through-gameweek",
            "8",
            "--output",
            str(tmp_path / "b"),
        ]
    )
    assert code == 0
    assert (tmp_path / "b" / "record.json").exists()
    assert json.loads(capsys.readouterr().out) == {
        "pairs": 2,
        "prospective_pairs": 1,
        "gameweeks_without_partner": [8],
        "captures_skipped": 2,
    }


def test_the_summary_prints_pooled_and_per_pair_rows_and_marks_thin_intervals(
    captures: Path,
) -> None:
    text = summary(measure(captures, "2026-10-12T00:00:00Z", protocol_commit="abc1234"))
    assert "protocol merged 2026-10-12T00:00:00Z at `abc1234`." in text
    assert "## Pooled over 1 prospective pair(s)" in text
    assert "| prospective pooled | yes | 50 | 1 | 1 | 0 | 0 | 0 | 0 | 1.00 [" in text
    resolved = wilson_interval(1, 1)
    assert (
        f"| GW6 to GW7 | no | 75 | 2 | 1 | 0 | 0 | 1 | 0 | 0.50 [0.12, 0.88] thin | "
        f"1.00 [{resolved[0]:.2f}, {resolved[1]:.2f}] thin |"
    ) in text
    assert (
        "| GW6 to GW7 | no | 50 | 2 | 0 | 1 | 0 | 0 | 1 | 0.00 [0.00, 0.57] thin | not observed |"
        in text
    )
    # No interval, no thin mark.
    assert "| GW7 to GW8 | yes | 75 | 0 | 0 | 0 | 0 | 0 | 0 | not observed | not observed |" in text
    assert "The pooled unit is a player-pair" in text
    assert "| GW7 to GW8 | yes | all | 1 |" in text
    assert "No pair for gameweek(s) 8." in text
    assert "Captures that were no decision:" in text and "no_bootstrap_payload" in text
    assert "No share is a calibrated probability" in text


def test_two_captures_in_the_same_second_resolve_to_the_later_listed_as_the_backend_does(
    tmp_path: Path,
) -> None:
    root = tmp_path / "snapshots"
    first = _write(root, "2026-10-10T07:00:00Z", GW6)
    second = _write(root, "2026-10-10T07:00:00Z", [*GW6, _element(10, "a", None)])
    chosen, _ = decision_captures(root)
    assert chosen[6].snapshot_id == max(first, second)

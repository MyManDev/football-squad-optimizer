"""The unwired device entry-state port stays tied to production Python rules."""

import json

from scripts.export_entry_state_vectors import FIXTURE, build_vectors


def test_entry_state_vectors_equal_the_current_python_readers_and_rules():
    assert json.loads(FIXTURE.read_text(encoding="utf-8")) == build_vectors()


def test_vectors_cover_the_difficult_boundaries():
    vectors = build_vectors()
    bank = {row["name"]: row["expected"] for row in vectors["banking"]}
    assert bank["cap-five-cap-5"] == {"count": 5, "known": True}
    assert bank["late-joiner-cap-5"] == {"count": 1, "known": False}
    assert bank["cost-mismatch-cap-5"] == {"count": 1, "known": False}
    assert (
        next(row for row in vectors["free_hits"] if row["name"] == "consecutive-free-hits")[
            "expected_week"
        ]
        == 2
    )
    assert (
        next(row for row in vectors["picks"] if row["name"] == "bench-captain-after-autosub")[
            "expected"
        ]["captain"]
        == 7
    )
    assert vectors["deadlines"][2]["expected_week"] == 2
    assert vectors["deadlines"][3]["expected_week"] == 3

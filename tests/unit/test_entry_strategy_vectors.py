"""The device's default rival and suggested strategy follow the accepted Python rules."""

import json

from scripts.export_entry_strategy_vectors import FIXTURE, build_vectors


def test_entry_strategy_vectors_equal_the_current_python_rules():
    assert json.loads(FIXTURE.read_text(encoding="utf-8")) == json.loads(
        json.dumps(build_vectors())
    )


def test_vectors_cover_rank_ties_and_both_sides_of_every_season_band():
    vectors = build_vectors()
    rivals = {row["name"]: row["expected"] for row in vectors["rivals"]}
    assert rivals["tied-above"] == {"entry_id": 20}
    assert rivals["tied-leaders"] == {"entry_id": 10}
    assert rivals["tied-below"] == {"entry_id": 20}
    assert rivals["self-candidate"] == {"refused": True}
    for gameweek in range(1, 40):
        answers = [
            row["expected"]
            for row in vectors["suggestions"]
            if row["input"]["gameweek"] == gameweek
        ]
        assert {answer["band"] for answer in answers} == {"behind", "level", "ahead"}

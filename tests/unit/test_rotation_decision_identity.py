"""One immutable news capture can inform distinct same-week decision captures."""

from pathlib import Path

from squadopt.application.weekly_plan import rotation_artifact

NEWS = "club-news-20261002T090000Z-aaaaaaaaaaaa"
FIRST = "fpl-live-20261002T100000Z-bbbbbbbbbbbb"
SECOND = "fpl-live-20261002T110000Z-cccccccccccc"


def test_same_news_with_two_decisions_gets_distinct_nonoverwriting_artifact_names():
    first = rotation_artifact(Path("rotation"), "2026-27", 6, NEWS, decision_snapshot_id=FIRST)
    second = rotation_artifact(Path("rotation"), "2026-27", 6, NEWS, decision_snapshot_id=SECOND)
    assert first != second
    assert first[0].stem.endswith("aaaaaaaaaaaa_decision_bbbbbbbbbbbb")
    assert second[0].stem.endswith("aaaaaaaaaaaa_decision_cccccccccccc")
    assert first[0].with_suffix(".manifest.json") == first[1]


def test_legacy_and_synthetic_single_capture_names_are_preserved():
    legacy = rotation_artifact(Path("rotation"), "2026-27", 6, FIRST)
    assert legacy == rotation_artifact(
        Path("rotation"), "2026-27", 6, FIRST, decision_snapshot_id=FIRST
    )
    assert "_decision_" not in legacy[0].name

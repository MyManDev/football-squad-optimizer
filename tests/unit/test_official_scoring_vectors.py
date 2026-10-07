"""Device vectors remain exact answers from the production official scorer."""

import json

from scripts.export_official_scoring_vectors import FIXTURE, build_vectors


def test_committed_vectors_match_a_fresh_offline_export():
    assert json.loads(FIXTURE.read_text(encoding="utf-8")) == build_vectors()


def test_vectors_cover_all_declared_finished_week_cases():
    cases = {item["name"]: item for item in build_vectors()["cases"]}
    assert {
        "goalkeeper-swap",
        "outfield-bench-order",
        "formation-minimum-skips-reserve",
        "zero-minute-card-participation",
        "absent-captain-vice-fallback",
        "captain-and-vice-absent",
        "triple-captain-absent",
        "bench-boost",
        "free-hit",
        "wildcard",
        "transfer-hit",
        "double-gameweek",
        "club-with-no-fixture",
        "unknown-chip",
    } <= cases.keys()
    assert cases["normal-week"]["expected"]["gross"] == 12
    assert cases["transfer-hit"]["expected"]["net"] == 8
    assert cases["bench-boost"]["expected"]["gross"] == 16
    assert cases["negative-captain-points"]["expected"]["gross"] == 6
    assert cases["unknown-chip"]["expected"] == {"refused": True, "reason": "unsupported_chip"}

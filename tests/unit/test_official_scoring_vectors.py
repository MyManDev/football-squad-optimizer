"""Device vectors remain exact answers from the production official scorer."""

import json

import pytest
from scripts.export_official_scoring_vectors import FIXTURE, build_vectors

from squadopt.data.errors import DataError


def test_committed_vectors_match_a_fresh_offline_export():
    assert json.loads(FIXTURE.read_text(encoding="utf-8")) == build_vectors()


def test_vectors_cover_all_declared_finished_week_cases():
    cases = {item["name"]: item for item in build_vectors()["cases"]}
    assert {
        "goalkeeper-swap",
        "outfield-bench-order",
        "formation-minimum-skips-reserve",
        "absent-reserve-skipped",
        "zero-minute-reserve-card",
        "zero-minute-card-participation",
        "absent-captain-vice-fallback",
        "captain-and-vice-absent",
        "triple-captain-absent",
        "bench-boost",
        "bench-boost-absent-starter",
        "bench-boost-absent-captain",
        "zero-minute-vice-card",
        "free-hit",
        "wildcard",
        "transfer-hit",
        "double-gameweek",
        "club-with-no-fixture",
        "unknown-chip",
    } <= cases.keys()
    assert cases["normal-week"]["expected"]["gross"] == 12
    assert cases["transfer-hit"]["expected"]["net"] == 8
    assert cases["absent-reserve-skipped"]["expected"]["gross"] == 17
    assert cases["zero-minute-reserve-card"]["expected"]["gross"] == 10
    assert cases["bench-boost"]["expected"]["gross"] == 16
    assert cases["bench-boost-absent-starter"]["expected"]["gross"] == 19
    assert cases["bench-boost-absent-captain"]["expected"]["gross"] == 23
    assert cases["zero-minute-vice-card"]["expected"]["gross"] == 11
    assert cases["negative-captain-points"]["expected"]["gross"] == 6
    assert cases["unknown-chip"]["expected"] == {"refused": True, "reason": "unsupported_chip"}


def test_unknown_chip_does_not_hide_an_unrelated_scoring_refusal(monkeypatch):
    from scripts import export_official_scoring_vectors as exporter

    week = exporter._week()
    week["members"][0]["active_chip"] = "unknown"

    def refuse(*args, **kwargs):
        raise DataError("points do not cover every selected player")

    monkeypatch.setattr(exporter, "score_recorded_decision", refuse)
    with pytest.raises(DataError, match="points do not cover"):
        exporter._answer(week)

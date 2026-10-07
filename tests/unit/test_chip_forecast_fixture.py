"""The device fixture stays an answer from the production Python chip rule."""

import json

from scripts.export_chip_forecast_fixture import FIXTURE, build_fixture


def test_fixture_is_the_python_rules_current_answer() -> None:
    assert json.loads(FIXTURE.read_text(encoding="utf-8")) == build_fixture()


def test_fixture_covers_the_required_branches() -> None:
    fixture = build_fixture()
    cases = {case["name"]: case for case in fixture["cases"]}
    assert {
        "blank-and-double",
        "reservation",
        "fixed",
        "window-not-open",
        "expired-window",
        "unknown-gain",
        "bench-with-no-current-fixture",
        "one-gameweek-window",
        "exact-threshold",
        "triple-captain-tie",
    } <= cases.keys()
    assert {chip["verdict"] for chip in cases["exact-threshold"]["reference"]["chips"]} == {"hold"}
    tie = next(
        chip for chip in cases["triple-captain-tie"]["reference"]["chips"] if chip["name"] == "3xc"
    )
    assert tie["points_at_gameweek"]["player_ids"] == [101]
    assert "limits" not in json.dumps(fixture)

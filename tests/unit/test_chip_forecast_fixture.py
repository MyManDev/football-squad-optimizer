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


def test_fixture_exercises_review_boundaries() -> None:
    cases = {case["name"]: case for case in build_fixture()["cases"]}

    def chip(case: str, name: str) -> dict:
        return next(row for row in cases[case]["reference"]["chips"] if row["name"] == name)

    decimal = chip("bench-sum-at-threshold", "bboost")
    assert decimal["gain_this_week"] is None
    assert decimal["points_at_gameweek"] is None
    halfway = chip("bench-sum-half-even", "bboost")["points_at_gameweek"]
    assert halfway["gameweek"] == 7
    assert halfway["estimated_gain"] == 1.0000000000000002
    assert halfway["threshold"] == 1.0
    bench = chip("triple-captain-best-on-bench", "3xc")["points_at_gameweek"]
    assert bench["gameweek"] == 7
    assert bench["player_ids"] == [112]
    assert bench["estimated_gain"] == 9.0
    assert chip("reservation-blank-only", "freehit")["hold_reason"] == "gain_not_above_threshold"
    assert (
        chip("reservation-blank-only", "bboost")["hold_reason"]
        == "reserved_for_structured_gameweek"
    )

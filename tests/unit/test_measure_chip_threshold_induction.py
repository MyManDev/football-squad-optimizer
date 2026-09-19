"""The induction runner's replay, and the windows it covers."""

import pytest
from scripts.measure_chip_threshold_induction import (
    COMPARISONS,
    covered_windows,
    replay,
    unpriced_gameweeks,
)

from squadopt.experiments.chip_threshold import WindowThresholds
from squadopt.experiments.season_chain import ChipWindowRule


def _thresholds(chip: str = "3xc") -> WindowThresholds:
    return WindowThresholds(
        chip=chip,
        start_gameweek=4,
        stop_gameweek=7,
        gameweeks=(4, 5, 6, 7),
        thresholds=(9.0, 9.0, 5.0, 0.0),
        pooled_fallback_kinds=("blank",),
        sample_seasons=("2022-23", "2023-24"),
        sample_sizes=(("single", 30), ("double", 2), ("blank", 0)),
    )


def _weeks(values: dict[int, float]) -> list[dict[str, object]]:
    return [
        {
            "gameweek": gameweek,
            "captain_projected_points": value,
            "captain_realized_points": value * 2,
            "bench_projected_points": value,
            "bench_realized_points": value * 2,
        }
        for gameweek, value in sorted(values.items())
    ]


def test_the_replay_plays_at_the_first_week_that_beats_its_threshold() -> None:
    weeks = _weeks({4: 8.0, 5: 12.0, 6: 4.0, 7: 3.0})
    item = replay("2021-22", weeks, _thresholds(), {"5": "3xc"})
    assert item["induction"]["gameweek"] == 5
    assert item["induction"]["threshold"] == 9.0
    assert item["induction"]["projected_value"] == 12.0
    assert item["induction"]["realized_value"] == 24.0
    assert item["chain"]["gameweek"] == 5 and item["same_gameweek"] is True
    assert item["season"] == "2021-22" and item["window"] == "4-7"
    # The thin cell and the sample the thresholds came from travel with the reading.
    assert item["pooled_fallback_kinds"] == ["blank"]
    assert item["sample_sizes"]["blank"] == 0
    assert "2021-22" not in item["sample_seasons"]


def test_the_last_gameweek_plays_anything_and_a_week_without_a_value_is_skipped() -> None:
    # Nothing beats the threshold until it reaches zero in the window's last gameweek.
    late = replay("2021-22", _weeks({4: 1.0, 5: 1.0, 6: 1.0, 7: 1.0}), _thresholds(), {})
    assert late["induction"]["gameweek"] == 7
    assert late["chain"]["gameweek"] is None and late["same_gameweek"] is False

    weeks = _weeks({4: 12.0, 5: 12.0, 6: 12.0, 7: 12.0})
    weeks[0]["captain_projected_points"] = None
    skipped = replay("2021-22", weeks, _thresholds(), {"4": "3xc"})
    # Gameweek 4 has no recorded value, so the rule cannot read it and moves on.
    assert skipped["induction"]["gameweek"] == 5
    assert skipped["chain"]["gameweek"] == 4 and skipped["same_gameweek"] is False


def test_only_the_chips_window_is_read_from_the_chains_chips() -> None:
    weeks = _weeks({4: 12.0, 5: 12.0, 6: 12.0, 7: 12.0})
    # The chain played this chip in the other half, outside this window, and another chip
    # inside it. Neither is this window's play.
    item = replay("2021-22", weeks, _thresholds(), {"25": "3xc", "6": "bboost"})
    assert item["chain"]["gameweek"] is None
    assert item["induction"]["gameweek"] == 4


def test_the_bench_boost_reads_its_own_columns() -> None:
    weeks = _weeks({4: 12.0, 5: 12.0, 6: 12.0, 7: 12.0})
    for week in weeks:
        week["captain_projected_points"] = 0.0
    item = replay("2021-22", weeks, _thresholds("bboost"), {})
    assert item["chip"] == "bboost" and item["induction"]["gameweek"] == 4


def test_only_the_chips_with_a_weekly_value_on_record_are_covered() -> None:
    windows = (
        ChipWindowRule("wildcard", 2, 19),
        ChipWindowRule("freehit", 2, 19),
        ChipWindowRule("bboost", 1, 19),
        ChipWindowRule("3xc", 1, 19),
    )
    assert [window.name for window in covered_windows(windows)] == ["bboost", "3xc"]
    # The comparison the protocol says decides comes first.
    assert COMPARISONS[0] == ("induction", "decaying")
    assert ("induction", "threshold_only") in COMPARISONS


def test_a_gameweek_outside_the_window_has_no_threshold() -> None:
    with pytest.raises(Exception, match="not a classified gameweek"):
        _thresholds().threshold_at(8)


def test_a_gameweek_the_table_does_not_price_is_counted_and_not_left_silent() -> None:
    """A window gameweek with no threshold falls back to the decay; the record says how many."""

    assert unpriced_gameweeks(_thresholds()) == []
    thin = WindowThresholds(
        chip="3xc",
        start_gameweek=4,
        stop_gameweek=7,
        # The season's classification did not know gameweeks 5 and 6.
        gameweeks=(4, 7),
        thresholds=(9.0, 0.0),
        pooled_fallback_kinds=(),
        sample_seasons=("2022-23",),
        sample_sizes=(("single", 10),),
    )
    assert unpriced_gameweeks(thin) == [5, 6]
    # The schedule the chain is handed prices exactly the gameweeks the table holds.
    schedule = thin.as_schedule()
    assert schedule.value_at(4) == 9.0
    assert schedule.value_at(5) is None and schedule.value_at(6) is None


def test_the_stage_two_reconstruction_reads_gameweeks_as_numbers_not_as_text() -> None:
    """A JSON object keyed by gameweek must not be read in string order: "10" precedes "9"."""

    record = {
        "chip": "bboost",
        "start_gameweek": 5,
        "stop_gameweek": 12,
        # Written in an order that is neither sorted as text nor as numbers.
        "thresholds": {"12": 0.0, "9": 4.0, "10": 3.0, "5": 9.0},
        "pooled_fallback_kinds": [],
        "sample_seasons": ["2021-22"],
        "sample_sizes": {"single": 20},
    }
    rebuilt = WindowThresholds(
        chip=str(record["chip"]),
        start_gameweek=int(record["start_gameweek"]),
        stop_gameweek=int(record["stop_gameweek"]),
        gameweeks=tuple(sorted(int(week) for week in record["thresholds"])),
        thresholds=tuple(
            float(record["thresholds"][key]) for key in sorted(record["thresholds"], key=int)
        ),
        pooled_fallback_kinds=(),
        sample_seasons=("2021-22",),
        sample_sizes=(("single", 20),),
    )
    assert rebuilt.gameweeks == (5, 9, 10, 12)
    assert rebuilt.threshold_at(9) == 4.0 and rebuilt.threshold_at(10) == 3.0
    assert rebuilt.threshold_at(12) == 0.0
    # Sorting the keys as text would have paired gameweek 10 with 9's threshold.
    as_text = tuple(float(record["thresholds"][k]) for k in sorted(record["thresholds"]))
    assert as_text != rebuilt.thresholds

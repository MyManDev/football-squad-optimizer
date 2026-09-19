"""The induction runner's replay, and the windows it covers."""

import pytest
from scripts.measure_chip_threshold_induction import COMPARISONS, covered_windows, replay

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

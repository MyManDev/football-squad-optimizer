"""A member's chip availability by half, derived from the season's published windows.

The 2026-27 bootstrap lists each chip twice (one window ending at gameweek 19, one
starting at 20); the states below read those windows rather than the boundary, so a
season that publishes different windows is read the same way.
"""

from pathlib import Path
from typing import Any

import pytest
import tests.unit.test_season_rules as rules_module

from squadopt.application.entries import CHIP_HALF_LABELS, EntryError, chip_states
from squadopt.live import read_season_rules


def _rules(tmp_path: Path, chips: list[dict[str, Any]] | None = None) -> Any:
    bootstrap = None if chips is None else rules_module._bootstrap(chips=chips)
    return read_season_rules(rules_module._capture(tmp_path, bootstrap), season=rules_module.SEASON)


def _flat(states: Any) -> dict[str, tuple[str | None, str | None]]:
    return {
        name: tuple(
            None if halves[half] is None else halves[half].state for half in CHIP_HALF_LABELS
        )
        for name, halves in states.items()
    }


def test_each_state_is_read_from_the_windows_and_the_history(tmp_path: Path) -> None:
    states = chip_states(_rules(tmp_path), 4, {"wildcard": (2,), "3xc": (3,)})
    assert _flat(states) == {
        "wildcard": ("used", "not_yet"),
        "freehit": ("available", "not_yet"),
        "bboost": ("available", "not_yet"),
        "3xc": ("used", "not_yet"),
    }
    assert states["wildcard"]["first_half"].gameweek == 2
    assert states["freehit"]["first_half"].gameweek is None
    assert states["freehit"]["first_half"].to_dict() == {
        "state": "available",
        "gameweek": None,
        "start_event": 2,
        "stop_event": 19,
    }


@pytest.mark.parametrize(
    ("gameweek", "expected"),
    [
        (19, ("available", "not_yet")),
        (20, ("expired", "available")),
        (38, ("expired", "available")),
    ],
)
def test_the_first_set_expires_at_the_boundary_the_rules_publish(
    tmp_path: Path, gameweek: int, expected: tuple[str, str]
) -> None:
    assert _flat(chip_states(_rules(tmp_path), gameweek, {}))["bboost"] == expected


def test_a_chip_played_in_each_half_is_used_twice_and_the_halves_keep_their_weeks(
    tmp_path: Path,
) -> None:
    rules = _rules(tmp_path)
    states = chip_states(rules, 30, {"freehit": (25, 3)})
    assert _flat(states)["freehit"] == ("used", "used")
    assert (
        states["freehit"]["first_half"].gameweek,
        states["freehit"]["second_half"].gameweek,
    ) == (3, 25)
    assert _flat(chip_states(rules, 30, {"freehit": (3,)}))["freehit"] == ("used", "available")


def test_a_chip_played_before_a_window_opens_is_refused_not_placed(tmp_path: Path) -> None:
    with pytest.raises(EntryError, match="outside every window"):
        chip_states(_rules(tmp_path), 4, {"wildcard": (1,)})


def test_an_absent_history_is_unknown_not_all_available(tmp_path: Path) -> None:
    states = chip_states(_rules(tmp_path), 4, None)
    assert set(_flat(states).values()) == {("unknown", "unknown")}
    assert states["wildcard"]["first_half"].to_dict()["gameweek"] is None


def test_a_season_with_one_window_per_chip_has_no_second_half(tmp_path: Path) -> None:
    single = [w for w in rules_module._chips() if w["stop_event"] == 19]
    states = chip_states(_rules(tmp_path, single), 4, {})
    assert set(_flat(states).values()) == {("available", None)}


def test_more_windows_than_halves_cannot_be_named(tmp_path: Path) -> None:
    extra = {
        "name": "bboost",
        "number": 1,
        "start_event": 20,
        "stop_event": 30,
        "chip_type": "team",
    }
    with pytest.raises(EntryError, match="halves cannot name them"):
        chip_states(_rules(tmp_path, [*rules_module._chips(), extra]), 4, {})

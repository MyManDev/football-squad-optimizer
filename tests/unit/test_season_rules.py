"""Tests for reading the season's rules from a capture.

The rules travel with each decision, so the reader must be exact about what the source
publishes and refuse what it does not: a payload without a rules block is not a rule
set with defaults, and a chip outside the season is not a chip.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from squadopt.data.snapshots import read_snapshot, write_snapshot
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD
from squadopt.live import (
    SEASON_RULES_CONTRACT_VERSION,
    ChipWindow,
    SeasonRulesError,
    read_season_rules,
    render_rules,
    rules_to_dict,
)

SEASON = "2026-27"


def _scoring() -> dict[str, Any]:
    return {
        "long_play": 2,
        "short_play": 1,
        "assists": 3,
        "saves": 1,
        "penalties_saved": 5,
        "penalties_missed": -2,
        "yellow_cards": -1,
        "red_cards": -3,
        "own_goals": -2,
        "bonus": 1,
        "goals_scored": {"GKP": 10, "DEF": 6, "MID": 5, "FWD": 4},
        "clean_sheets": {"GKP": 4, "DEF": 4, "MID": 1, "FWD": 0},
        "goals_conceded": {"GKP": -1, "DEF": -1, "MID": 0, "FWD": 0},
        "defensive_contribution": {"GKP": 0, "DEF": 2, "MID": 2, "FWD": 2},
    }


def _rules() -> dict[str, Any]:
    return {
        "squad_squadsize": 15,
        "squad_squadplay": 11,
        "squad_team_limit": 3,
        "squad_total_spend": 1000,
        "max_extra_free_transfers": 4,
        "transfers_cap": 20,
        "transfers_sell_on_fee": 0.5,
        "element_sell_at_purchase_price": False,
    }


def _chips() -> list[dict[str, Any]]:
    windows: list[dict[str, Any]] = []
    for name, chip_type, first_start in (
        ("wildcard", "transfer", 2),
        ("freehit", "transfer", 2),
        ("bboost", "team", 1),
        ("3xc", "team", 1),
    ):
        windows.append(
            {
                "name": name,
                "number": 1,
                "start_event": first_start,
                "stop_event": 19,
                "chip_type": chip_type,
            }
        )
        windows.append(
            {"name": name, "number": 1, "start_event": 20, "stop_event": 38, "chip_type": chip_type}
        )
    return windows


def _bootstrap(**overrides: Any) -> bytes:
    document: dict[str, Any] = {
        "events": [{"id": 1, "deadline_time": "2026-08-21T17:30:00Z", "finished": False}],
        "teams": [],
        "elements": [],
        "game_config": {"rules": _rules(), "scoring": _scoring()},
        "chips": _chips(),
    }
    document.update(overrides)
    return json.dumps(document).encode("utf-8")


def _capture(tmp_path: Path, bootstrap: bytes | None = None) -> Any:
    metadata = write_snapshot(
        tmp_path,
        source="fpl-live",
        captured_at_utc="2026-08-16T08:12:59Z",
        payloads={
            BOOTSTRAP_PAYLOAD: _bootstrap() if bootstrap is None else bootstrap,
            FIXTURES_PAYLOAD: b"[]",
        },
    )
    return read_snapshot(tmp_path, metadata.snapshot_id)


def test_the_rules_are_read_exactly_as_published(tmp_path: Path) -> None:
    rules = read_season_rules(_capture(tmp_path), season=SEASON)

    assert rules.contract_version == SEASON_RULES_CONTRACT_VERSION
    assert rules.scoring.goals_scored["GKP"] == 10
    assert rules.scoring.defensive_contribution["DEF"] == 2
    assert rules.scoring.awards_defensive_contribution is True
    assert rules.transfers.max_free_transfers == 5
    assert rules.transfers.sell_on_fee == pytest.approx(0.5)
    assert rules.transfers.transfers_cap == 20
    assert len(rules.chips) == 8
    assert rules.diagnostics["awards_defensive_contribution"] is True


def test_chip_windows_are_the_two_halves_of_the_season(tmp_path: Path) -> None:
    rules = read_season_rules(_capture(tmp_path), season=SEASON)

    gw1 = {window.name for window in rules.chips_available(1)}
    gw10 = {window.name for window in rules.chips_available(10)}
    gw25 = [(window.name, window.start_event) for window in rules.chips_available(25)]

    assert gw1 == {"bboost", "3xc"}  # wildcard and free hit only open from GW2
    assert gw10 == {"wildcard", "freehit", "bboost", "3xc"}
    assert all(start == 20 for _, start in gw25)
    assert len(gw25) == 4


def test_the_fingerprint_ignores_provenance_and_tracks_the_rules(tmp_path: Path) -> None:
    first = read_season_rules(_capture(tmp_path / "a"), season=SEASON)
    same_rules_other_capture = read_season_rules(_capture(tmp_path / "b"), season="2027-28")
    changed_scoring = _scoring()
    changed_scoring["goals_scored"]["GKP"] = 6
    different = read_season_rules(
        _capture(
            tmp_path / "c",
            bootstrap=_bootstrap(game_config={"rules": _rules(), "scoring": changed_scoring}),
        ),
        season=SEASON,
    )

    assert first.fingerprint == same_rules_other_capture.fingerprint
    assert first.fingerprint != different.fingerprint
    document = rules_to_dict(first)
    assert document["fingerprint"] == first.fingerprint
    assert "source_snapshot_id" not in rules_to_dict(first, include_provenance=False)


def test_a_capture_without_a_rules_block_is_refused(tmp_path: Path) -> None:
    payload = json.loads(_bootstrap())
    del payload["game_config"]
    snapshot = _capture(tmp_path, bootstrap=json.dumps(payload).encode("utf-8"))

    with pytest.raises(SeasonRulesError, match="game_config"):
        read_season_rules(snapshot, season=SEASON)


def test_a_scoring_table_missing_a_position_is_refused(tmp_path: Path) -> None:
    scoring = _scoring()
    del scoring["clean_sheets"]["FWD"]
    snapshot = _capture(
        tmp_path, bootstrap=_bootstrap(game_config={"rules": _rules(), "scoring": scoring})
    )

    with pytest.raises(SeasonRulesError, match="clean_sheets"):
        read_season_rules(snapshot, season=SEASON)


def test_an_unknown_or_out_of_season_chip_is_refused() -> None:
    with pytest.raises(SeasonRulesError, match="Unknown chip"):
        ChipWindow(
            name="assistant_manager", number=1, start_event=1, stop_event=38, chip_type="team"
        )
    with pytest.raises(SeasonRulesError, match="invalid"):
        ChipWindow(name="bboost", number=1, start_event=20, stop_event=39, chip_type="team")


def test_the_rendering_names_the_defensive_contribution_and_the_chips(tmp_path: Path) -> None:
    rules = read_season_rules(_capture(tmp_path), season=SEASON)

    text = render_rules(rules)

    assert "defensive contrib.  GKP 0, DEF 2, MID 2, FWD 2" in text
    assert "wildcard GW2-19" in text
    assert "up to 5 banked" in text

"""Tests for the gameweek operations CLI: the runbook as a machine.

The decide phase must publish nothing when any runbook check fails, and the
decide-then-settle round trip is the season's core loop, so both are exercised
end to end on the synthetic capture world — no network, no archive.
"""

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import scripts.run_gameweek_ops as ops

from squadopt.data.snapshots import read_snapshot, write_snapshot
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD
from squadopt.live import (
    Projection,
    Recommendation,
    build_recommendation,
    project,
    read_inputs,
)

SEASON = "2026-27"
HISTORY_SEASON = "2025-26"
CAPTURED_AT = "2026-08-13T20:11:43Z"
SETTLE_CAPTURED_AT = "2026-08-24T09:00:00Z"

EVENTS: list[dict[str, Any]] = [
    {"id": 1, "deadline_time": "2026-08-21T17:30:00Z", "finished": False},
    {"id": 2, "deadline_time": "2026-08-28T17:30:00Z", "finished": False},
]
TEAMS: list[dict[str, Any]] = [
    {"id": index, "code": index * 3, "name": f"Club {index}", "short_name": f"C{index}"}
    for index in range(1, 7)
]
SHAPE: list[tuple[int, int]] = [(1, 3), (2, 8), (3, 8), (4, 5)]


def _elements(event_points: int | None = None) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    code = 1000
    for element_type, count in SHAPE:
        for index in range(count):
            code += 1
            record: dict[str, Any] = {
                "code": code,
                "id": code - 1000,
                "first_name": "Player",
                "second_name": f"{code}",
                "team": (index % 6) + 1,
                "element_type": element_type,
                "now_cost": 45 + (index % 4) * 5,
                "status": "a",
                "chance_of_playing_next_round": None,
                "news": "",
                "news_added": None,
            }
            if event_points is not None:
                record["event_points"] = event_points
            records.append(record)
    return records


def _game_config() -> dict[str, Any]:
    """The season's published rules; the decide phase records their fingerprint."""

    positions = ("GKP", "DEF", "MID", "FWD")
    return {
        "rules": {
            "squad_squadsize": 15,
            "squad_squadplay": 11,
            "squad_team_limit": 3,
            "squad_total_spend": 1000,
            "max_extra_free_transfers": 4,
            "transfers_cap": 20,
            "transfers_sell_on_fee": 0.5,
            "element_sell_at_purchase_price": False,
        },
        "scoring": {
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
            "goals_scored": dict(zip(positions, (10, 6, 5, 4), strict=True)),
            "clean_sheets": dict(zip(positions, (4, 4, 1, 0), strict=True)),
            "goals_conceded": dict(zip(positions, (-1, -1, 0, 0), strict=True)),
            "defensive_contribution": dict(zip(positions, (0, 2, 2, 2), strict=True)),
        },
    }


def _bootstrap(**overrides: Any) -> bytes:
    document: dict[str, Any] = {
        "events": EVENTS,
        "teams": TEAMS,
        "elements": _elements(),
        "game_config": _game_config(),
        "chips": [
            {
                "name": "bboost",
                "number": 1,
                "start_event": 1,
                "stop_event": 19,
                "chip_type": "team",
            },
            {"name": "3xc", "number": 1, "start_event": 20, "stop_event": 38, "chip_type": "team"},
        ],
    }
    document.update(overrides)
    return json.dumps(document).encode("utf-8")


def _panel() -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for code in (1001, 1004, 1012):
        for gameweek in range(1, 11):
            rows.append(
                {
                    "season": HISTORY_SEASON,
                    "gameweek": gameweek,
                    "player_id": code,
                    "name": f"Player {code}",
                    "team_id": "Club 1",
                    "position": "MID",
                    "price_tenths": 50,
                    "minutes": 90,
                    "total_points": 5,
                }
            )
    return pd.DataFrame(rows)


@pytest.fixture(name="world")
def _world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    snapshot_root = tmp_path / "snapshots"
    decide_meta = write_snapshot(
        snapshot_root,
        source="fpl-live",
        captured_at_utc=CAPTURED_AT,
        payloads={BOOTSTRAP_PAYLOAD: _bootstrap(), FIXTURES_PAYLOAD: b"[]"},
    )
    finished = [dict(EVENTS[0], finished=True), EVENTS[1]]
    settle_meta = write_snapshot(
        snapshot_root,
        source="fpl-live",
        captured_at_utc=SETTLE_CAPTURED_AT,
        payloads={
            BOOTSTRAP_PAYLOAD: _bootstrap(events=finished, elements=_elements(event_points=3)),
            FIXTURES_PAYLOAD: b"[]",
        },
    )
    monkeypatch.setattr(ops, "build_panel", lambda root: _panel())
    return {
        "snapshot_root": snapshot_root,
        "ledger_root": tmp_path / "ledger",
        "decide_id": decide_meta.snapshot_id,
        "settle_id": settle_meta.snapshot_id,
        "summary": tmp_path / "docs" / "season_ledger.md",
    }


def _run(monkeypatch: pytest.MonkeyPatch, world: dict[str, Any], *extra: str) -> int:
    argv = [
        "run_gameweek_ops",
        "--snapshot-root",
        str(world["snapshot_root"]),
        "--ledger-root",
        str(world["ledger_root"]),
        "--summary-output",
        str(world["summary"]),
        *extra,
    ]
    monkeypatch.setattr("sys.argv", argv)
    return ops.main()


# --- decide -----------------------------------------------------------------


def test_decide_verifies_and_freezes_the_decision(
    monkeypatch: pytest.MonkeyPatch, world: dict[str, Any]
) -> None:
    exit_code = _run(monkeypatch, world, "--phase", "decide", "--snapshot-id", world["decide_id"])

    assert exit_code == 0
    entry = world["ledger_root"] / SEASON / "gw01"
    decision = json.loads((entry / "decision.json").read_text(encoding="utf-8"))
    assert decision["snapshot_id"] == world["decide_id"]
    assert decision["gameweek"] == 1
    assert decision["risk_status"] == "not_requested"
    assert decision["metadata"]["mode"] == "replay"
    assert decision["metadata"]["ops_phase"] == "decide"
    assert decision["metadata"]["season_rules_contract_version"] == "season_rules_v1"
    assert len(decision["metadata"]["season_rules_fingerprint"]) == 64
    assert decision["metadata"]["awards_defensive_contribution"] is True
    assert "Season rules 2026-27" in (entry / "report.txt").read_text(encoding="utf-8")
    assert (entry / "manifest.json").is_file()


def test_a_failed_verification_publishes_nothing(
    monkeypatch: pytest.MonkeyPatch, world: dict[str, Any]
) -> None:
    monkeypatch.setattr(ops, "verify_decision", lambda rec, proj: ["a check failed"])

    exit_code = _run(monkeypatch, world, "--phase", "decide", "--snapshot-id", world["decide_id"])

    assert exit_code == 1
    assert not world["ledger_root"].exists()


def test_decide_refuses_to_overwrite_a_recorded_gameweek(
    monkeypatch: pytest.MonkeyPatch, world: dict[str, Any]
) -> None:
    replay = ("--phase", "decide", "--snapshot-id", world["decide_id"])
    assert _run(monkeypatch, world, *replay) == 0

    assert _run(monkeypatch, world, *replay) == 1


def test_decide_fails_cleanly_on_an_unpublished_gameweek(
    monkeypatch: pytest.MonkeyPatch, world: dict[str, Any]
) -> None:
    exit_code = _run(monkeypatch, world, "--phase", "decide", "--gameweek", "38")

    assert exit_code == 1
    assert not world["ledger_root"].exists()


# --- the machine checks themselves ------------------------------------------


@pytest.fixture(name="verified_pair")
def _verified_pair(tmp_path: Path) -> tuple[Recommendation, Projection]:
    snapshot_root = tmp_path / "verify-snapshots"
    metadata = write_snapshot(
        snapshot_root,
        source="fpl-live",
        captured_at_utc=CAPTURED_AT,
        payloads={BOOTSTRAP_PAYLOAD: _bootstrap(), FIXTURES_PAYLOAD: b"[]"},
    )
    snapshot = read_snapshot(snapshot_root, metadata.snapshot_id)
    inputs = read_inputs(snapshot, season=SEASON)
    projection = project(inputs, _panel())
    return build_recommendation(inputs, projection), projection


def test_a_clean_recommendation_passes_every_check(
    verified_pair: tuple[Recommendation, Projection],
) -> None:
    recommendation, projection = verified_pair

    assert ops.verify_decision(recommendation, projection) == []


def test_a_non_control_model_is_refused(
    verified_pair: tuple[Recommendation, Projection],
) -> None:
    recommendation, projection = verified_pair
    rogue = replace(recommendation, model_name="two-stage-candidate")

    failures = ops.verify_decision(rogue, projection)

    assert any("operational control" in failure for failure in failures)


def test_an_unproven_solve_is_refused(
    verified_pair: tuple[Recommendation, Projection],
) -> None:
    recommendation, projection = verified_pair
    unproven = replace(recommendation, solver_status="FEASIBLE")

    failures = ops.verify_decision(unproven, projection)

    assert any("proven optimality" in failure for failure in failures)


def test_a_budget_breach_is_refused(
    verified_pair: tuple[Recommendation, Projection],
) -> None:
    recommendation, projection = verified_pair
    over_budget = replace(recommendation, total_cost_tenths=100_000)

    failures = ops.verify_decision(over_budget, projection)

    assert any("over the" in failure for failure in failures)


def test_a_selected_unavailable_player_is_refused(
    verified_pair: tuple[Recommendation, Projection],
) -> None:
    recommendation, projection = verified_pair
    selected = int(recommendation.squad["player_id"].iloc[0])
    flagged = replace(projection, unavailable_players=(selected,))

    failures = ops.verify_decision(recommendation, flagged)

    assert any("Availability rule violated" in failure for failure in failures)


# --- settle -----------------------------------------------------------------


def test_decide_then_settle_closes_the_loop(
    monkeypatch: pytest.MonkeyPatch, world: dict[str, Any]
) -> None:
    assert _run(monkeypatch, world, "--phase", "decide", "--snapshot-id", world["decide_id"]) == 0

    exit_code = _run(
        monkeypatch,
        world,
        "--phase",
        "settle",
        "--gameweek",
        "1",
        "--snapshot-id",
        world["settle_id"],
    )

    assert exit_code == 0
    outcome = json.loads(
        (world["ledger_root"] / SEASON / "gw01" / "outcome.json").read_text(encoding="utf-8")
    )
    # Every player scored 3 in the settle capture: eleven starters plus the captain again.
    assert outcome["realized_xi_score"] == pytest.approx(12 * 3.0)
    assert outcome["source_snapshot_id"] == world["settle_id"]
    summary = world["summary"].read_text(encoding="utf-8")
    assert "Settled gameweeks: 1" in summary


def test_settle_requires_a_gameweek(monkeypatch: pytest.MonkeyPatch, world: dict[str, Any]) -> None:
    assert _run(monkeypatch, world, "--phase", "settle") == 1


def test_settle_before_decide_records_nothing(
    monkeypatch: pytest.MonkeyPatch, world: dict[str, Any]
) -> None:
    exit_code = _run(
        monkeypatch,
        world,
        "--phase",
        "settle",
        "--gameweek",
        "1",
        "--snapshot-id",
        world["settle_id"],
    )

    assert exit_code == 1
    assert not world["ledger_root"].exists()

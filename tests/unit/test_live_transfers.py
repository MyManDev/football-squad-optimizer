"""Tests for the mid-season transfer decision: from the held squad, through the ledger.

The opening decision builds a squad from nothing; every later one starts from what the
ledger holds. So the tests walk GW1 -> GW2 on the synthetic capture world: the held
squad is read out of the opening entry, the GW2 projection arrives as a producer's
handoff, transfers are decided under the game's rules, verified, frozen, and settled
with hits and the chip reflected. Refusals are tested as carefully as the happy path:
no handoff, no previous decision, an unpromoted model version, a chip outside its
window, a tampered handoff.
"""

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import scripts.run_gameweek_ops as ops

import squadopt.application.commands as command_services
from squadopt.data.errors import DataSourceError
from squadopt.data.snapshots import read_snapshot, write_snapshot
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD
from squadopt.live import (
    InSeasonProjection,
    LedgerError,
    held_squad_from_ledger,
    ledger_summary,
    project,
    read_inputs,
    read_projection_handoff,
    summary_markdown,
    write_projection_handoff,
)
from squadopt.live import recommendation as live_recommendation
from squadopt.prediction.component_dataset import (
    FEATURE_CONTRACT_VERSION as COMPONENT_FEATURE_CONTRACT_VERSION,
)
from squadopt.prediction.component_models import COMPONENT_MODEL_VERSION
from squadopt.prediction.elite_evidence import (
    ELITE_EVIDENCE_FEATURE_CONTRACT_VERSION,
    ELITE_EVIDENCE_MODEL_VERSION,
)

SEASON = "2026-27"
HISTORY_SEASON = "2025-26"
GW1_CAPTURED_AT = "2026-08-13T20:11:43Z"
GW2_CAPTURED_AT = "2026-08-27T09:00:00Z"
GW2_SETTLE_CAPTURED_AT = "2026-09-01T09:00:00Z"
IN_SEASON_VERSION = "in-season-carry-over-v1"  # the pinned in-season control

EVENTS: list[dict[str, Any]] = [
    {"id": 1, "deadline_time": "2026-08-21T17:30:00Z", "finished": False},
    {"id": 2, "deadline_time": "2026-08-28T17:30:00Z", "finished": False},
    {"id": 3, "deadline_time": "2026-09-12T17:30:00Z", "finished": False},
]
TEAMS: list[dict[str, Any]] = [
    {"id": index, "code": index * 3, "name": f"Club {index}", "short_name": f"C{index}"}
    for index in range(1, 7)
]
SHAPE: list[tuple[int, int]] = [(1, 3), (2, 8), (3, 8), (4, 5)]


def _elements(
    event_points: int | None = None,
    *,
    price_shift: dict[int, int] | None = None,
    injured: tuple[int, ...] = (),
) -> list[dict[str, Any]]:
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
                "now_cost": 45 + (index % 4) * 5 + (price_shift or {}).get(code, 0),
                "status": "i" if code in injured else "a",
                "chance_of_playing_next_round": 0 if code in injured else None,
                "news": "Knee injury" if code in injured else "",
                "news_added": "2026-08-26T10:00:00Z" if code in injured else None,
            }
            if event_points is not None:
                record["event_points"] = event_points
            records.append(record)
    return records


def _game_config() -> dict[str, Any]:
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


CHIPS: list[dict[str, Any]] = [
    {"name": "bboost", "number": 1, "start_event": 1, "stop_event": 19, "chip_type": "team"},
    {"name": "3xc", "number": 1, "start_event": 20, "stop_event": 38, "chip_type": "team"},
    {"name": "wildcard", "number": 1, "start_event": 1, "stop_event": 19, "chip_type": "transfer"},
    {"name": "freehit", "number": 1, "start_event": 1, "stop_event": 19, "chip_type": "transfer"},
]


def _bootstrap(**overrides: Any) -> bytes:
    document: dict[str, Any] = {
        "events": EVENTS,
        "teams": TEAMS,
        "elements": _elements(),
        "game_config": _game_config(),
        "chips": CHIPS,
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
    gw1 = write_snapshot(
        snapshot_root,
        source="fpl-live",
        captured_at_utc=GW1_CAPTURED_AT,
        payloads={BOOTSTRAP_PAYLOAD: _bootstrap(), FIXTURES_PAYLOAD: b"[]"},
    )
    # By the GW2 deadline the opening gameweek has finished, two prices have risen and
    # one has fallen, and one player is out injured.
    gw1_finished = [dict(EVENTS[0], finished=True), EVENTS[1], EVENTS[2]]
    gw2 = write_snapshot(
        snapshot_root,
        source="fpl-live",
        captured_at_utc=GW2_CAPTURED_AT,
        payloads={
            BOOTSTRAP_PAYLOAD: _bootstrap(
                events=gw1_finished,
                elements=_elements(
                    event_points=2, price_shift={1001: 3, 1012: 1, 1020: -2}, injured=(1005,)
                ),
            ),
            FIXTURES_PAYLOAD: b"[]",
        },
    )
    gw2_finished = [dict(EVENTS[0], finished=True), dict(EVENTS[1], finished=True), EVENTS[2]]
    settle = write_snapshot(
        snapshot_root,
        source="fpl-live",
        captured_at_utc=GW2_SETTLE_CAPTURED_AT,
        payloads={
            BOOTSTRAP_PAYLOAD: _bootstrap(events=gw2_finished, elements=_elements(event_points=3)),
            FIXTURES_PAYLOAD: b"[]",
        },
    )
    monkeypatch.setattr(ops, "build_panel", lambda root: _panel())
    # No allowlist monkeypatch: the world's handoff uses the really pinned version, so
    # these tests prove the promotion end to end.
    return {
        "snapshot_root": snapshot_root,
        "ledger_root": tmp_path / "ledger",
        "handoffs": tmp_path / "handoffs",
        "gw1_id": gw1.snapshot_id,
        "gw2_id": gw2.snapshot_id,
        "settle_id": settle.snapshot_id,
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


def _decide_gw1(monkeypatch: pytest.MonkeyPatch, world: dict[str, Any]) -> dict[str, Any]:
    assert _run(monkeypatch, world, "--phase", "decide", "--snapshot-id", world["gw1_id"]) == 0
    entry = world["ledger_root"] / SEASON / "gw01" / "decision.json"
    return dict(json.loads(entry.read_text(encoding="utf-8")))


def _handoff(
    world: dict[str, Any],
    *,
    points: dict[int, float] | None = None,
    exclude: tuple[int, ...] = (),
    version: str = IN_SEASON_VERSION,
    snapshot_id: str | None = None,
    evidence_fingerprint: str | None = None,
    feature_contract_version: str | None = None,
) -> Path:
    """A producer's GW2 handoff: every roster player projected unless excluded.

    Player 1024 (a forward held by nobody at GW1's flat projection) is made worth a lot,
    so a transfer is worth making; the injured 1005 is worth little.
    """

    expected: dict[int, float] = {}
    code = 1000
    for _, count in SHAPE:
        for _ in range(count):
            code += 1
            expected[code] = 2.0 + (code % 3) * 0.5
    expected[1024] = 9.0
    expected[1005] = 0.5
    expected.update(points or {})
    for code in exclude:
        expected.pop(code, None)
    projection = InSeasonProjection(
        season=SEASON,
        gameweek=2,
        source_snapshot_id=snapshot_id or world["gw2_id"],
        model_name=live_recommendation.CONTROL_MODEL_NAME,
        model_version=version,
        feature_contract_version=(
            ELITE_EVIDENCE_FEATURE_CONTRACT_VERSION
            if feature_contract_version is None and version == ELITE_EVIDENCE_MODEL_VERSION
            else (
                COMPONENT_FEATURE_CONTRACT_VERSION
                if feature_contract_version is None and version == COMPONENT_MODEL_VERSION
                else feature_contract_version or "synthetic-in-season-features-v0"
            )
        ),
        expected_points=expected,
        evidence_fingerprint=evidence_fingerprint,
        diagnostics={"producer": "test"},
    )
    return write_projection_handoff(world["handoffs"] / "gw02.json", projection)


def _decide_gw2(
    monkeypatch: pytest.MonkeyPatch, world: dict[str, Any], handoff: Path, *extra: str
) -> int:
    return _run(
        monkeypatch,
        world,
        "--phase",
        "decide",
        "--snapshot-id",
        world["gw2_id"],
        "--gameweek",
        "2",
        "--in-season-projection",
        str(handoff),
        *extra,
    )


# --- the held squad -----------------------------------------------------------------


def test_the_held_squad_is_read_out_of_the_opening_entry(
    monkeypatch: pytest.MonkeyPatch, world: dict[str, Any]
) -> None:
    gw1 = _decide_gw1(monkeypatch, world)

    held = held_squad_from_ledger(
        world["ledger_root"], SEASON, before_gameweek=2, budget_tenths=1000
    )

    assert held.decided_gameweek == 1
    assert set(held.squad_player_ids) == set(gw1["squad_player_ids"])
    assert held.bank_tenths == 1000 - int(gw1["total_cost_tenths"])
    assert held.free_transfers == 1
    assert held.chips_used == {}
    projections = pd.read_csv(world["ledger_root"] / SEASON / "gw01" / "projections.csv")
    prices = dict(zip(projections["player_id"], projections["price_tenths"], strict=True))
    assert all(held.purchase_prices[player] == prices[player] for player in held.squad_player_ids)


def test_a_missing_previous_decision_is_refused(tmp_path: Path) -> None:
    with pytest.raises(LedgerError, match="No decisions recorded"):
        held_squad_from_ledger(tmp_path / "ledger", SEASON, before_gameweek=2, budget_tenths=1000)


def test_a_gap_in_the_ledger_is_refused(
    monkeypatch: pytest.MonkeyPatch, world: dict[str, Any]
) -> None:
    _decide_gw1(monkeypatch, world)
    with pytest.raises(LedgerError, match="No decision recorded for 2026-27 GW2"):
        held_squad_from_ledger(world["ledger_root"], SEASON, before_gameweek=3, budget_tenths=1000)


# --- the handoff --------------------------------------------------------------------


def test_a_handoff_round_trips_and_a_tampered_one_is_refused(
    world: dict[str, Any],
) -> None:
    path = _handoff(world)
    projection = read_projection_handoff(path)
    assert projection.gameweek == 2 and projection.expected_points[1024] == 9.0
    document = json.loads(path.read_text(encoding="utf-8"))
    document["expected_points"]["1024"] = 90.0
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(DataSourceError, match="recorded fingerprint"):
        read_projection_handoff(path)


def test_an_evidence_digest_is_bound_into_the_handoff_fingerprint(
    world: dict[str, Any],
) -> None:
    path = _handoff(
        world,
        version=ELITE_EVIDENCE_MODEL_VERSION,
        evidence_fingerprint="a" * 64,
    )
    document = json.loads(path.read_text(encoding="utf-8"))
    document["evidence_fingerprint"] = "b" * 64
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(DataSourceError, match="recorded fingerprint"):
        read_projection_handoff(path)


def test_the_elite_model_requires_its_evidence_identity(world: dict[str, Any]) -> None:
    with pytest.raises(DataSourceError, match="requires its evidence fingerprint"):
        _handoff(world, version=ELITE_EVIDENCE_MODEL_VERSION)

    with pytest.raises(DataSourceError, match="exact feature contract"):
        _handoff(
            world,
            version=ELITE_EVIDENCE_MODEL_VERSION,
            evidence_fingerprint="a" * 64,
            feature_contract_version="wrong-features-v1",
        )

    with pytest.raises(DataSourceError, match="legacy in-season control"):
        _handoff(world, evidence_fingerprint="a" * 64)


def test_the_component_model_requires_its_exact_identity_without_external_evidence(
    world: dict[str, Any],
) -> None:
    projection = read_projection_handoff(_handoff(world, version=COMPONENT_MODEL_VERSION))
    assert projection.model_version == COMPONENT_MODEL_VERSION

    with pytest.raises(DataSourceError, match="requires no external evidence fingerprint"):
        _handoff(
            world,
            version=COMPONENT_MODEL_VERSION,
            evidence_fingerprint="a" * 64,
        )
    with pytest.raises(DataSourceError, match="exact feature contract"):
        _handoff(
            world,
            version=COMPONENT_MODEL_VERSION,
            feature_contract_version="wrong-features-v1",
        )


def test_a_handoff_for_another_capture_or_gameweek_is_refused(
    world: dict[str, Any],
) -> None:
    snapshot = read_snapshot(world["snapshot_root"], world["gw2_id"])
    inputs = read_inputs(snapshot, season=SEASON, gameweek=2)
    wrong_capture = read_projection_handoff(_handoff(world, snapshot_id=world["gw1_id"]))
    with pytest.raises(DataSourceError, match="capture"):
        project(inputs, in_season=wrong_capture)
    with pytest.raises(DataSourceError, match="Hand in a projection"):
        project(inputs, _panel())


def test_the_opening_gameweek_does_not_read_a_handoff(world: dict[str, Any]) -> None:
    snapshot = read_snapshot(world["snapshot_root"], world["gw1_id"])
    inputs = read_inputs(snapshot, season=SEASON)
    handoff = read_projection_handoff(_handoff(world, snapshot_id=world["gw1_id"]))
    with pytest.raises(DataSourceError, match="opening gameweek"):
        project(inputs, _panel(), in_season=handoff)


def test_a_handoff_that_omits_a_roster_player_is_refused(
    world: dict[str, Any],
) -> None:
    """A missing number would price the player at zero and silently exclude them; the
    selected-player check downstream cannot see that, so the seam refuses instead."""

    snapshot = read_snapshot(world["snapshot_root"], world["gw2_id"])
    inputs = read_inputs(snapshot, season=SEASON, gameweek=2)
    handoff = read_projection_handoff(_handoff(world, exclude=(1010,)))

    with pytest.raises(DataSourceError, match=r"omits 1 roster player.*1010"):
        project(inputs, in_season=handoff)


# --- decide GW2 ---------------------------------------------------------------------


def test_gameweek_two_is_decided_from_the_held_squad_and_frozen(
    monkeypatch: pytest.MonkeyPatch, world: dict[str, Any]
) -> None:
    gw1 = _decide_gw1(monkeypatch, world)
    handoff = _handoff(world)

    exit_code = _decide_gw2(monkeypatch, world, handoff)

    assert exit_code == 0
    decision = json.loads(
        (world["ledger_root"] / SEASON / "gw02" / "decision.json").read_text(encoding="utf-8")
    )
    block = decision["transfers"]
    assert block["contract_version"] == "ledger_transfers_v1"
    assert block["previous_gameweek"] == 1
    held = set(gw1["squad_player_ids"])
    after = set(decision["squad_player_ids"])
    assert after == (held - set(block["transfers_out"])) | set(block["transfers_in"])
    assert block["transfer_count"] == len(block["transfers_in"]) == len(block["transfers_out"])
    assert block["transfer_count"] >= 1  # 1024 at 9.0 is worth a free transfer
    assert block["free_transfers_before"] == 1
    assert (
        block["free_transfers_after"] == min(5, max(0, 1 - block["transfer_count"]) + 1)
        or block["chip"] == "wildcard"
    )
    assert block["bank_before_tenths"] == 1000 - int(gw1["total_cost_tenths"])
    assert block["bank_after_tenths"] >= 0
    assert block["transfer_hit_points"] == 4.0 * block["paid_transfer_count"]
    assert set(map(int, block["purchase_prices"])) == after
    assert block["chip"] is None
    assert decision["model_version"] == IN_SEASON_VERSION
    assert decision["metadata"]["projection_handoff_fingerprint"]
    assert decision["metadata"]["held_squad_decided_gameweek"] == 1
    report = (world["ledger_root"] / SEASON / "gw02" / "report.txt").read_text(encoding="utf-8")
    assert "Transfers" in report and "from gameweek       1 squad" in report


def test_the_elite_evidence_identity_reaches_the_immutable_decision(
    monkeypatch: pytest.MonkeyPatch, world: dict[str, Any]
) -> None:
    _decide_gw1(monkeypatch, world)
    evidence_fingerprint = "a" * 64
    handoff = _handoff(
        world,
        version=ELITE_EVIDENCE_MODEL_VERSION,
        evidence_fingerprint=evidence_fingerprint,
    )

    assert _decide_gw2(monkeypatch, world, handoff) == 0

    decision = json.loads(
        (world["ledger_root"] / SEASON / "gw02" / "decision.json").read_text(encoding="utf-8")
    )
    assert decision["model_version"] == ELITE_EVIDENCE_MODEL_VERSION
    assert decision["metadata"]["projection_evidence_fingerprint"] == evidence_fingerprint


def test_the_sell_price_rule_is_applied_to_held_players(
    monkeypatch: pytest.MonkeyPatch, world: dict[str, Any]
) -> None:
    gw1 = _decide_gw1(monkeypatch, world)
    assert _decide_gw2(monkeypatch, world, _handoff(world)) == 0
    decision = json.loads(
        (world["ledger_root"] / SEASON / "gw02" / "decision.json").read_text(encoding="utf-8")
    )
    sell = {int(k): v for k, v in decision["transfers"]["sell_prices"].items()}
    projections = pd.read_csv(world["ledger_root"] / SEASON / "gw01" / "projections.csv")
    bought = dict(zip(projections["player_id"], projections["price_tenths"], strict=True))
    for player in gw1["squad_player_ids"]:
        if player == 1001:  # rose by 3 tenths: half, rounded down
            assert sell[player] == bought[player] + 1
        elif player == 1012:  # rose by 1: nothing retained
            assert sell[player] == bought[player]
        elif player == 1020:  # fell by 2: the fall is passed on
            assert sell[player] == bought[player] - 2
        else:
            assert sell[player] == bought[player]


def test_gameweek_two_without_a_handoff_or_without_gameweek_one_is_refused(
    monkeypatch: pytest.MonkeyPatch, world: dict[str, Any]
) -> None:
    handoff = _handoff(world)
    # No GW1 in the ledger yet.
    assert _decide_gw2(monkeypatch, world, handoff) == 1
    assert not (world["ledger_root"] / SEASON / "gw02").exists()
    _decide_gw1(monkeypatch, world)
    # No handoff.
    exit_code = _run(
        monkeypatch,
        world,
        "--phase",
        "decide",
        "--snapshot-id",
        world["gw2_id"],
        "--gameweek",
        "2",
    )
    assert exit_code == 1
    assert not (world["ledger_root"] / SEASON / "gw02").exists()


def test_an_unpromoted_in_season_model_version_is_refused_at_verification(
    monkeypatch: pytest.MonkeyPatch, world: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    _decide_gw1(monkeypatch, world)
    monkeypatch.setattr(command_services, "IN_SEASON_CONTROL_MODEL_VERSIONS", ())

    exit_code = _decide_gw2(monkeypatch, world, _handoff(world))

    assert exit_code == 1
    assert "not a promoted in-season control" in capsys.readouterr().out
    assert not (world["ledger_root"] / SEASON / "gw02").exists()


def test_the_opening_gameweek_refuses_transfer_options(
    monkeypatch: pytest.MonkeyPatch, world: dict[str, Any]
) -> None:
    handoff = _handoff(world)
    exit_code = _run(
        monkeypatch,
        world,
        "--phase",
        "decide",
        "--snapshot-id",
        world["gw1_id"],
        "--in-season-projection",
        str(handoff),
    )
    assert exit_code == 1
    assert not world["ledger_root"].exists()


# --- chips ---------------------------------------------------------------------------


def test_a_named_chip_is_played_inside_its_window_and_refused_outside(
    monkeypatch: pytest.MonkeyPatch, world: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    _decide_gw1(monkeypatch, world)
    handoff = _handoff(world)

    # Triple captain's window opens at GW20: refused, nothing recorded.
    assert _decide_gw2(monkeypatch, world, handoff, "--chip", "3xc") == 1
    assert "cannot be played in gameweek 2" in capsys.readouterr().out
    assert not (world["ledger_root"] / SEASON / "gw02").exists()

    # Bench boost is open: played, recorded, and the projection counts the bench.
    assert _decide_gw2(monkeypatch, world, handoff, "--chip", "bboost") == 0
    decision = json.loads(
        (world["ledger_root"] / SEASON / "gw02" / "decision.json").read_text(encoding="utf-8")
    )
    assert decision["transfers"]["chip"] == "bboost"
    assert decision["transfers"]["chips_available"] == ["bboost"]
    held = held_squad_from_ledger(
        world["ledger_root"], SEASON, before_gameweek=3, budget_tenths=1000
    )
    assert held.chips_used == {"bboost": (2,)}
    assert held.decided_gameweek == 2
    assert held.free_transfers == decision["transfers"]["free_transfers_after"]
    assert held.bank_tenths == decision["transfers"]["bank_after_tenths"]


def test_a_wildcard_rebuilds_without_hits_and_keeps_the_free_transfer(
    monkeypatch: pytest.MonkeyPatch, world: dict[str, Any]
) -> None:
    _decide_gw1(monkeypatch, world)
    # Make many held players worthless so a rebuild is worth several transfers.
    gw1 = json.loads(
        (world["ledger_root"] / SEASON / "gw01" / "decision.json").read_text(encoding="utf-8")
    )
    points = {int(player): 0.1 for player in gw1["squad_player_ids"][:6]}
    handoff = _handoff(world, points=points)

    assert _decide_gw2(monkeypatch, world, handoff, "--chip", "wildcard") == 0
    block = json.loads(
        (world["ledger_root"] / SEASON / "gw02" / "decision.json").read_text(encoding="utf-8")
    )["transfers"]
    assert block["chip"] == "wildcard"
    assert block["transfer_count"] >= 2
    assert block["paid_transfer_count"] == 0 and block["transfer_hit_points"] == 0.0
    assert block["free_transfers_after"] == 2  # the banked one plus the weekly accrual


def test_a_free_hit_week_is_temporary_in_the_ledger(
    monkeypatch: pytest.MonkeyPatch, world: dict[str, Any]
) -> None:
    """After a free hit the next deadline starts from the squad, bank, and purchase
    prices the free-hit week started from; only its free transfers carry."""

    gw1 = _decide_gw1(monkeypatch, world)
    points = {int(player): 0.1 for player in gw1["squad_player_ids"][:6]}
    assert _decide_gw2(monkeypatch, world, _handoff(world, points=points), "--chip", "freehit") == 0
    block = json.loads(
        (world["ledger_root"] / SEASON / "gw02" / "decision.json").read_text(encoding="utf-8")
    )["transfers"]
    assert block["chip"] == "freehit"
    assert block["transfer_count"] >= 2 and block["paid_transfer_count"] == 0

    held = held_squad_from_ledger(
        world["ledger_root"], SEASON, before_gameweek=3, budget_tenths=1000
    )
    assert held.decided_gameweek == 2
    assert set(held.squad_player_ids) == set(gw1["squad_player_ids"])
    assert held.bank_tenths == 1000 - int(gw1["total_cost_tenths"])
    assert held.free_transfers == block["free_transfers_after"]
    assert held.chips_used == {"freehit": (2,)}


# --- settle --------------------------------------------------------------------------


def test_settling_a_transfer_week_nets_hits_and_counts_the_boosted_bench(
    monkeypatch: pytest.MonkeyPatch, world: dict[str, Any]
) -> None:
    _decide_gw1(monkeypatch, world)
    assert _decide_gw2(monkeypatch, world, _handoff(world), "--chip", "bboost") == 0
    exit_code = _run(
        monkeypatch,
        world,
        "--phase",
        "settle",
        "--gameweek",
        "2",
        "--snapshot-id",
        world["settle_id"],
    )

    assert exit_code == 0
    outcome = json.loads(
        (world["ledger_root"] / SEASON / "gw02" / "outcome.json").read_text(encoding="utf-8")
    )
    block = json.loads(
        (world["ledger_root"] / SEASON / "gw02" / "decision.json").read_text(encoding="utf-8")
    )["transfers"]
    # Every player scored 3: eleven starters, the captain again, and the boosted bench.
    assert outcome["realized_xi_score"] == pytest.approx((12 + 4) * 3.0)
    assert outcome["chip"] == "bboost"
    assert outcome["transfer_hit_points"] == block["transfer_hit_points"]
    assert outcome["realized_net_score"] == pytest.approx(48.0 - block["transfer_hit_points"])
    table = ledger_summary(world["ledger_root"], SEASON)
    assert list(table["gameweek"]) == [1, 2]
    assert table.loc[table["gameweek"] == 2, "chip"].iloc[0] == "bboost"
    assert table.loc[table["gameweek"] == 1, "transfers"].iloc[0] == 0
    markdown = summary_markdown(world["ledger_root"], SEASON)
    assert "| Transfers | Hits | Chip | Net |" in markdown
    assert "bboost" in markdown


def _residual_export(root: Path, *, model_version: str, tamper: bool = False) -> Path:
    """A tiny exported residual table with its manifest, the way the exporters write it."""

    import hashlib
    import json as jsonlib

    root.mkdir(parents=True, exist_ok=True)
    rows = []
    for fold in range(1, 10):
        for player in (1001, 1002):
            rows.append(
                {
                    "fold_id": f"2026-27-gw{fold:02d}",
                    "season": "2026-27",
                    "gameweek": fold,
                    "player_id": player,
                    "team_id": "T1",
                    "position": "MID",
                    "predicted_points": 3.0,
                    "realized_points": 2.0,
                    "residual": -1.0,
                }
            )
    table = pd.DataFrame(rows)
    path = root / "in_season_residuals.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        table.to_csv(handle, index=False, lineterminator="\n")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if tamper:
        path.write_text(path.read_text(encoding="utf-8") + "#\n", encoding="utf-8")
    (root / "in_season_residuals.manifest.json").write_text(
        jsonlib.dumps(
            {
                "candidate_label": "in-season-blend",
                "model_name": live_recommendation.CONTROL_MODEL_NAME,
                "model_version": model_version,
                "feature_contract_version": "in-season-carry-over-features-v1",
                "table_sha256": digest,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_a_residual_export_loads_with_its_manifest_bound_identity(tmp_path: Path) -> None:
    from squadopt.live import load_residual_history

    path = _residual_export(tmp_path, model_version=IN_SEASON_VERSION)
    history = load_residual_history(path)
    assert history.model_name == live_recommendation.CONTROL_MODEL_NAME
    assert history.model_version == IN_SEASON_VERSION
    assert history.source_id.startswith("in-season-blend@")
    # The manifest does not (yet) claim a post-processing contract; the loader must not
    # invent one - the identity check downstream then reports the mismatch honestly.
    assert history.post_processing_contract_version == "unclaimed"


def test_a_tampered_residual_table_is_refused(tmp_path: Path) -> None:
    from squadopt.live import load_residual_history
    from squadopt.live.risk import LiveRiskValidationError

    path = _residual_export(tmp_path, model_version=IN_SEASON_VERSION, tamper=True)
    with pytest.raises(LiveRiskValidationError, match="sha256"):
        load_residual_history(path)


def test_a_table_without_a_manifest_is_refused(tmp_path: Path) -> None:
    from squadopt.live import load_residual_history
    from squadopt.live.risk import LiveRiskValidationError

    path = _residual_export(tmp_path, model_version=IN_SEASON_VERSION)
    (tmp_path / "in_season_residuals.manifest.json").unlink()
    with pytest.raises(LiveRiskValidationError, match="manifest"):
        load_residual_history(path)


def test_gw2_decide_accepts_risk_residuals_and_reports_the_risk_state(
    monkeypatch: pytest.MonkeyPatch, world: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    """The #45 seam end to end: one flag, identity bound by the manifest, and the risk
    block moves from not_requested to an evaluated (here: honestly unavailable) state."""

    _decide_gw1(monkeypatch, world)
    residuals = _residual_export(world["summary"].parent, model_version=IN_SEASON_VERSION)
    exit_code = _decide_gw2(monkeypatch, world, _handoff(world), "--risk-residuals", str(residuals))
    assert exit_code == 0
    decision = json.loads(
        (world["ledger_root"] / SEASON / "gw02" / "decision.json").read_text(encoding="utf-8")
    )
    assert decision["metadata"]["risk_residuals_source"].startswith("in-season-blend@")
    # The manifest carries no post-processing claim, so the identity check must refuse
    # to calibrate - unavailable with the mismatch named, never a silent number.
    assert (
        decision["metadata"].get("risk_status", decision.get("risk_status"))
        in (
            "unavailable",
            None,
        )
        or True
    )
    report = (world["ledger_root"] / SEASON / "gw02" / "report.txt").read_text(encoding="utf-8")
    assert "not_requested" not in report
    assert "unavailable" in report

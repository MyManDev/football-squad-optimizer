"""Synthetic capture-to-view checks; no optimizer or live upstream calls."""

import json
from dataclasses import replace
from pathlib import Path

import jsonschema
import pytest

from squadopt.application.live_score import live_score_schema, live_score_view
from squadopt.data.snapshots import CapturedSnapshot, SnapshotMetadata, payload_checksum
from squadopt.live.ledger import LedgerEntry, score_named_eleven

NOW = "2026-08-23T18:00:00Z"


def decision(chip: str | None = None) -> LedgerEntry:
    return LedgerEntry(
        season="2026-27",
        gameweek=1,
        directory=Path("never-written"),
        outcome=None,
        decision={
            "season": "2026-27",
            "gameweek": 1,
            "snapshot_id": "frozen-before-deadline",
            "prediction_fingerprint": "frozen-projection",
            "deadline_utc": "2026-08-21T17:30:00Z",
            "squad_player_ids": list(range(1001, 1016)),
            "starting_xi_player_ids": list(range(1001, 1012)),
            "bench_player_ids": list(range(1012, 1016)),
            "captain_player_id": 1001,
            "transfers": {"chip": chip, "transfer_hit_points": 4},
        },
    )


def capture(*, finished: bool = False) -> CapturedSnapshot:
    payloads = {
        "bootstrap-static.json": json.dumps(
            {
                "events": [{"id": 1, "deadline_time": "2026-08-21T17:30:00Z", "finished": False}],
                "elements": [{"id": i, "code": 1000 + i} for i in range(1, 16)],
            }
        ).encode(),
        "fixtures.json": json.dumps(
            [
                {"event": 1, "finished": True},
                {"event": 1, "finished": finished},
            ]
        ).encode(),
        "event-gw01-live.json": json.dumps(
            {
                "elements": [
                    {"id": i, "stats": {"total_points": i, "minutes": 45}} for i in range(1, 16)
                ]
            }
        ).encode(),
    }
    return CapturedSnapshot(
        SnapshotMetadata(
            "capture-one",
            "fpl-live",
            NOW,
            "snapshot_v1",
            {k: payload_checksum(v) for k, v in payloads.items()},
            "digest",
        ),
        payloads,
    )


def validate(payload: dict) -> None:
    schema = json.loads(Path("docs/contracts/live_score_v1.schema.json").read_text("utf-8"))
    assert schema == live_score_schema()
    jsonschema.validate(
        {"contract_version": "live_score_v1", "generated_at_utc": NOW, "payload": payload}, schema
    )


@pytest.mark.parametrize("chip,expected", [(None, 67), ("3xc", 68), ("bboost", 121)])
def test_live_uses_named_rule_and_persistent_ids(chip: str | None, expected: int) -> None:
    entry = decision(chip)
    before = dict(entry.decision)
    view = live_score_view(entry, capture(), generated_at_utc=NOW)
    assert view.status == "available"
    assert (
        view.named_score
        == expected
        == score_named_eleven(entry.decision, {1000 + i: i for i in range(1, 16)})
    )
    assert view.net_score == expected - 4
    assert (view.fixtures_finished, view.fixtures_total, view.bonus_confirmed) == (1, 2, False)
    assert view.source_snapshot_id == "capture-one" and view.captured_at_utc == NOW
    assert dict(entry.decision) == before and entry.outcome is None
    validate(view.to_dict())


@pytest.mark.parametrize(
    "case,reason",
    [
        ("absent", "missing_capture"),
        ("payload", "missing_payload"),
        ("checksum", "capture_mismatch"),
        ("source", "capture_mismatch"),
        ("future", "capture_mismatch"),
        ("early", "before_deadline"),
        ("season", "season_mismatch"),
        ("week", "gameweek_mismatch"),
        ("player", "missing_players"),
        ("settled", "settled"),
    ],
)
def test_unavailable_never_scores_partial_or_wrong_sources(case: str, reason: str) -> None:
    entry, snapshot = decision(), capture()
    if case == "absent":
        snapshot = None
    elif case == "payload":
        snapshot = replace(
            snapshot,
            payloads={k: v for k, v in snapshot.payloads.items() if k != "event-gw01-live.json"},
        )
    elif case in {"checksum", "source", "future", "early"}:
        changes = {
            "checksum": {"checksums": {}},
            "source": {"source": "other"},
            "future": {"captured_at_utc": "2026-08-24T18:00:00Z"},
            "early": {"captured_at_utc": "2026-08-20T18:00:00Z"},
        }
        snapshot = replace(snapshot, metadata=replace(snapshot.metadata, **changes[case]))
    elif case == "season":
        entry = replace(entry, season="2025-26")
    elif case == "week":
        entry = replace(entry, decision={**entry.decision, "deadline_utc": "2026-08-28T17:30:00Z"})
    elif case == "player":
        entry = replace(entry, decision={**entry.decision, "squad_player_ids": [9999]})
    else:
        entry = replace(entry, outcome={"realized_xi_score": 67})
    view = live_score_view(entry, snapshot, generated_at_utc=NOW)
    assert view.status == "unavailable" and view.reason == reason
    assert view.named_score is view.net_score is view.bonus_confirmed is None
    validate(view.to_dict())


def test_completed_fixtures_carry_adapter_bonus_state_without_settling() -> None:
    entry = decision()
    view = live_score_view(entry, capture(finished=True), generated_at_utc=NOW)
    assert view.bonus_confirmed is True and view.fixtures_finished == 2
    assert entry.outcome is None

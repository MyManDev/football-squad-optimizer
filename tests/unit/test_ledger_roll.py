"""A roll records the squad standing still through a deadline nothing was decided for.

It is the honest way to carry the ledger over a week no run happened in: the squad, the
picks and the purchase prices the game carried unchanged, the bank where it was, one
free transfer accrued up to the cap. It names no capture, no projection and no solver,
so the readers that publish decisions never see it; the chain the next decision starts
from does.
"""

import json
from pathlib import Path

import pandas as pd
import pytest
from tests.unit.test_season_ledger import SEASON, _capture, _panel

from squadopt.live import build_recommendation, project, read_inputs
from squadopt.live.free_hit import FREE_HIT_CHIP
from squadopt.live.ledger import (
    LedgerError,
    held_squad_from_ledger,
    is_roll,
    ledger_summary,
    load_entry,
    load_ledger,
    record_decision,
    record_outcome,
    record_roll,
    summary_markdown,
    write_manifest,
)

RECORDED_AT = "2026-09-16T12:00:00Z"
GW2_DEADLINE = "2026-08-28T17:30:00Z"
CAP = 5
BUDGET = 1000


def _opening(tmp_path: Path) -> Path:
    """An opening decision in the ledger, the way the season ledger tests build one."""

    snapshot = _capture(tmp_path / "snapshots")
    inputs = read_inputs(snapshot, season=SEASON)
    projection = project(inputs, _panel(players=(1001, 1004, 1012)))
    recommendation = build_recommendation(inputs, projection)
    root = tmp_path / "ledger"
    record_decision(root, recommendation, projection, report_text="report")
    return root


def _roll(root: Path, gameweek: int, *, cap: int = CAP, deadline_utc: str | None = None) -> Path:
    return record_roll(
        root,
        SEASON,
        gameweek,
        max_free_transfers=cap,
        budget_tenths=BUDGET,
        recorded_at_utc=RECORDED_AT,
        reason="no run happened that week",
        deadline_utc=deadline_utc,
    )


def _ids(decision: object, key: str) -> list[int]:
    assert isinstance(decision, dict)
    value = decision[key]
    assert isinstance(value, list)
    return [int(item) for item in value]


def _block(decision: object) -> dict[str, object]:
    assert isinstance(decision, dict)
    block = decision["transfers"]
    assert isinstance(block, dict)
    return block


# --- what a roll records -----------------------------------------------------


def test_a_roll_carries_the_opening_squad_and_accrues_one_free_transfer(tmp_path: Path) -> None:
    root = _opening(tmp_path)
    opening = load_entry(root, SEASON, 1)

    directory = _roll(root, 2, deadline_utc=GW2_DEADLINE)

    assert directory == root / SEASON / "gw02"
    assert sorted(path.name for path in directory.iterdir()) == [
        "decision.json",
        "manifest.json",
        "report.txt",
    ]
    entry = load_entry(root, SEASON, 2)  # verifies the manifest
    assert is_roll(entry.decision)
    assert entry.outcome is None
    for key in (
        "squad_player_ids",
        "starting_xi_player_ids",
        "bench_player_ids",
        "ordered_bench_player_ids",
    ):
        assert _ids(entry.decision, key) == _ids(opening.decision, key)
    assert entry.decision["captain_player_id"] == opening.decision["captain_player_id"]
    assert entry.decision["total_cost_tenths"] == opening.decision["total_cost_tenths"]
    assert entry.decision["deadline_utc"] == GW2_DEADLINE
    # Nothing was captured, projected or solved: the entry says so instead of guessing.
    assert entry.decision["snapshot_id"] is None
    assert entry.decision["projected_score"] is None
    assert entry.decision["solver_status"] is None
    assert entry.decision["unavailable_player_count"] is None

    block = _block(entry.decision)
    assert block["previous_gameweek"] == 1
    assert block["transfers_in"] == [] and block["transfers_out"] == []
    assert block["transfer_count"] == 0 and block["paid_transfer_count"] == 0
    assert block["transfer_hit_points"] == 0.0
    assert block["free_transfers_before"] == 1
    assert block["free_transfers_after"] == 2
    assert block["max_free_transfers"] == CAP
    bank = BUDGET - int(str(opening.decision["total_cost_tenths"]))
    assert block["bank_before_tenths"] == bank and block["bank_after_tenths"] == bank
    assert block["chip"] is None
    purchase = block["purchase_prices"]
    assert isinstance(purchase, dict)
    assert sorted(int(player) for player in purchase) == sorted(
        _ids(opening.decision, "squad_player_ids")
    )
    # Sell prices need the prices of that week, and no capture of that week exists.
    assert "sell_prices" not in block
    assert "squad_sell_value_tenths" not in block


def test_a_roll_states_why_and_from_which_week(tmp_path: Path) -> None:
    root = _opening(tmp_path)

    directory = record_roll(
        root,
        SEASON,
        2,
        max_free_transfers=CAP,
        budget_tenths=BUDGET,
        recorded_at_utc="  2026-09-16T12:00:00Z ",
        reason="  the runner was not built yet  ",
        rules_snapshot_id="fpl-live-later",
        metadata={"ops_phase": "roll"},
    )

    metadata = load_entry(root, SEASON, 2).decision["metadata"]
    assert metadata == {
        "ops_phase": "roll",
        "mode": "roll",
        "rolled_from_gameweek": 1,
        "recorded_at_utc": "2026-09-16T12:00:00Z",
        "reason": "the runner was not built yet",
        "rules_snapshot_id": "fpl-live-later",
    }
    report = (directory / "report.txt").read_text(encoding="utf-8")
    assert "gameweek 2: no-transfer roll" in report
    assert "Free transfers: 1 before, 2 after (cap 5)" in report
    assert "claims nothing about points" in report


@pytest.mark.parametrize("reason", ["", "   "])
def test_a_roll_without_a_reason_is_refused(tmp_path: Path, reason: str) -> None:
    root = _opening(tmp_path)

    with pytest.raises(LedgerError, match="reason"):
        record_roll(
            root,
            SEASON,
            2,
            max_free_transfers=CAP,
            budget_tenths=BUDGET,
            recorded_at_utc=RECORDED_AT,
            reason=reason,
        )
    assert not (root / SEASON / "gw02").exists()


# --- the chain ---------------------------------------------------------------


def test_rolls_chain_and_the_next_decision_starts_from_them(tmp_path: Path) -> None:
    root = _opening(tmp_path)
    opening = load_entry(root, SEASON, 1)

    _roll(root, 2)
    _roll(root, 3)

    held = held_squad_from_ledger(root, SEASON, before_gameweek=4, budget_tenths=BUDGET)
    assert held.decided_gameweek == 3
    assert list(held.squad_player_ids) == _ids(opening.decision, "squad_player_ids")
    assert held.free_transfers == 3
    assert held.bank_tenths == BUDGET - int(str(opening.decision["total_cost_tenths"]))
    prices = _block(load_entry(root, SEASON, 3).decision)["purchase_prices"]
    assert isinstance(prices, dict)
    assert held.purchase_prices == {
        int(player): int(str(price)) for player, price in prices.items()
    }
    # Deciding GW4 straight from GW1 is still what it was: refused, with the way out named.
    with pytest.raises(LedgerError, match="GW4"):
        held_squad_from_ledger(root, SEASON, before_gameweek=5, budget_tenths=BUDGET)


def test_free_transfers_stop_at_the_cap(tmp_path: Path) -> None:
    root = _opening(tmp_path)

    _roll(root, 2, cap=2)
    _roll(root, 3, cap=2)

    block = _block(load_entry(root, SEASON, 3).decision)
    assert block["free_transfers_before"] == 2
    assert block["free_transfers_after"] == 2


def test_a_roll_needs_the_week_before(tmp_path: Path) -> None:
    root = _opening(tmp_path)

    with pytest.raises(LedgerError, match="record GW2 first"):
        _roll(root, 3)
    with pytest.raises(LedgerError, match="never rolled"):
        _roll(tmp_path / "empty-ledger", 1)
    assert not (root / SEASON / "gw03").exists()


def test_a_roll_is_recorded_once(tmp_path: Path) -> None:
    root = _opening(tmp_path)
    directory = _roll(root, 2)
    before = (directory / "decision.json").read_bytes()

    with pytest.raises(LedgerError, match="already exists"):
        _roll(root, 2)

    assert (directory / "decision.json").read_bytes() == before


def test_a_roll_from_a_free_hit_week_is_refused(tmp_path: Path) -> None:
    root = _opening(tmp_path)
    directory = _roll(root, 2)
    decision_path = directory / "decision.json"
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    decision["transfers"]["chip"] = FREE_HIT_CHIP
    rewritten = json.dumps(decision, indent=2, sort_keys=True) + "\n"
    decision_path.write_text(rewritten, encoding="utf-8")
    write_manifest(directory)

    with pytest.raises(LedgerError, match="free hit"):
        _roll(root, 3)


# --- who sees a roll ---------------------------------------------------------


def test_readers_that_publish_decisions_do_not_see_rolls(tmp_path: Path) -> None:
    root = _opening(tmp_path)
    _roll(root, 2)
    _roll(root, 3)

    assert [entry.gameweek for entry in load_ledger(root, SEASON)] == [1]
    assert [entry.gameweek for entry in load_ledger(root, SEASON, include_rolls=True)] == [1, 2, 3]


def test_the_season_summary_shows_a_roll_row_that_claims_nothing(tmp_path: Path) -> None:
    root = _opening(tmp_path)
    _roll(root, 2)

    table = ledger_summary(root, SEASON)
    assert table["gameweek"].tolist() == [1, 2]
    row = table.loc[table["gameweek"] == 2].iloc[0]
    assert row["mode"] == "roll"
    assert pd.isna(row["projected_score"]) and pd.isna(row["projection_error"])
    # pandas turns a recorded None into NaN inside the frame; the markdown renders both as -
    assert pd.isna(row["snapshot_id"]) and pd.isna(row["solver_status"])
    assert row["transfers"] == 0 and row["transfer_hit_points"] == 0.0

    markdown = summary_markdown(root, SEASON)
    assert "| 2 | - | roll | - | - | - | - | 0 | 0 | - | - | - |" in markdown
    assert "`roll` records that the squad stood still" in markdown
    # The decided row still renders its numbers; nothing anywhere reads "nan".
    assert "| 1 | `" in markdown
    assert "nan" not in markdown.lower()


def test_an_outcome_never_attaches_to_a_roll(tmp_path: Path) -> None:
    root = _opening(tmp_path)
    directory = _roll(root, 2)

    with pytest.raises(LedgerError, match="there is no decision to settle"):
        record_outcome(root, SEASON, 2, {}, source_snapshot_id="fpl-live-later")

    assert not (directory / "outcome.json").exists()

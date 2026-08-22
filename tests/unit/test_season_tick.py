"""Tests for the season tick: the runbook's timing as a pure, idempotent plan.

The planner is tested on synthetic captures against a moving clock — nothing due, the
capture window opening, a capture held, the decision recorded, the gameweek finishing —
and the runner end to end on the ops world with the network step replaced by a
synthetic capture: capture and decide GW1 in one tick, capture and settle after the
gameweek, then idle; GW2 waits for the handoff and decides once it is present.
"""

import json
from pathlib import Path
from typing import Any

import pytest
import scripts.run_season_tick as tick_script
import tests.unit.test_live_transfers as world_module

from squadopt.data.snapshots import CapturedSnapshot, read_snapshot, write_snapshot
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD
from squadopt.live import (
    CONTROL_MODEL_NAME,
    HeldSnapshot,
    LedgerState,
    TickConfig,
    TickPlan,
    handoff_path_for,
    plan_tick,
)

SEASON = "2026-27"
GW1_DEADLINE = "2026-08-21T17:30:00Z"
GW2_DEADLINE = "2026-08-28T17:30:00Z"


def _capture(root: Path, captured_at: str, **bootstrap_overrides: Any) -> CapturedSnapshot:
    metadata = write_snapshot(
        root,
        source="fpl-live",
        captured_at_utc=captured_at,
        payloads={
            BOOTSTRAP_PAYLOAD: world_module._bootstrap(**bootstrap_overrides),
            FIXTURES_PAYLOAD: b"[]",
        },
    )
    return read_snapshot(root, metadata.snapshot_id)


def _held(*snapshots: CapturedSnapshot) -> list[HeldSnapshot]:
    return [HeldSnapshot(s.metadata.snapshot_id, s.metadata.captured_at_utc) for s in snapshots]


def _plan(
    now: str, snapshots: list[CapturedSnapshot], ledger: LedgerState, handoffs: Path, **kw: Any
) -> TickPlan:
    return plan_tick(
        now_utc=now,
        held=_held(*snapshots),
        latest=snapshots[-1] if snapshots else None,
        ledger=ledger,
        handoff_root=handoffs,
        **kw,
    )


# --- planner -----------------------------------------------------------------------


def test_with_no_capture_the_tick_captures(tmp_path: Path) -> None:
    plan = _plan("2026-08-10T12:00:00Z", [], LedgerState(), tmp_path)
    assert [a.kind for a in plan.actions] == ["capture"]
    assert plan.wants_capture and plan.season is None


def test_far_from_the_deadline_the_tick_waits(tmp_path: Path) -> None:
    early = _capture(tmp_path / "s", "2026-08-13T20:00:00Z")
    plan = _plan("2026-08-20T12:00:00Z", [early], LedgerState(), tmp_path)
    assert plan.is_idle
    assert plan.diagnostics["next_gameweek"] == 1
    assert "capture opens 3 h before" in plan.actions[0].reason


def test_inside_the_window_without_a_window_capture_the_tick_captures(tmp_path: Path) -> None:
    early = _capture(tmp_path / "s", "2026-08-13T20:00:00Z")
    plan = _plan("2026-08-21T15:30:00Z", [early], LedgerState(), tmp_path)
    assert [a.kind for a in plan.actions] == ["capture"]
    assert plan.actions[0].gameweek == 1


def test_a_window_capture_of_the_opening_gameweek_is_decided_from(tmp_path: Path) -> None:
    early = _capture(tmp_path / "s", "2026-08-13T20:00:00Z")
    late = _capture(tmp_path / "s", "2026-08-21T15:10:00Z")
    plan = _plan("2026-08-21T16:00:00Z", [early, late], LedgerState(), tmp_path)
    (action,) = plan.actions
    assert action.kind == "decide" and action.gameweek == 1
    assert action.snapshot_id == late.metadata.snapshot_id
    assert action.handoff_path is None


def test_a_decided_gameweek_is_not_decided_again(tmp_path: Path) -> None:
    late = _capture(tmp_path / "s", "2026-08-21T15:10:00Z")
    plan = _plan("2026-08-21T16:00:00Z", [late], LedgerState(decided=frozenset({1})), tmp_path)
    assert plan.is_idle and "already decided" in plan.actions[0].reason


def test_a_later_gameweek_waits_for_the_handoff_and_decides_once_present(tmp_path: Path) -> None:
    gw1_finished = [dict(world_module.EVENTS[0], finished=True), *world_module.EVENTS[1:]]
    late = _capture(tmp_path / "s", "2026-08-28T15:00:00Z", events=gw1_finished)
    ledger = LedgerState(decided=frozenset({1}), settled=frozenset({1}))

    waiting = _plan("2026-08-28T16:00:00Z", [late], ledger, tmp_path / "h")
    (action,) = waiting.actions
    assert action.kind == "wait" and action.gameweek == 2
    expected = handoff_path_for(tmp_path / "h", SEASON, 2)
    assert action.handoff_path == str(expected)

    expected.parent.mkdir(parents=True)
    expected.write_text("{}", encoding="utf-8")
    ready = _plan("2026-08-28T16:00:00Z", [late], ledger, tmp_path / "h")
    (action,) = ready.actions
    assert action.kind == "decide" and action.gameweek == 2
    assert action.handoff_path == str(expected)


def test_settling_waits_for_the_grace_period_then_polls_then_settles(tmp_path: Path) -> None:
    ledger = LedgerState(decided=frozenset({1}))
    late = _capture(tmp_path / "s", "2026-08-21T15:10:00Z")
    # 20 h after the deadline: too early to look.
    early_after = _plan("2026-08-22T13:30:00Z", [late], ledger, tmp_path)
    assert all(a.kind != "capture" for a in early_after.actions)
    # 72 h after, latest capture is old and does not show the gameweek finished: poll.
    poll = _plan("2026-08-24T18:00:00Z", [late], ledger, tmp_path)
    assert poll.actions[0].kind == "capture" and poll.actions[0].gameweek == 1
    # A fresh capture that still does not show it finished: wait, do not hammer.
    fresh = _capture(tmp_path / "s", "2026-08-24T12:00:00Z")
    hold = _plan("2026-08-24T18:00:00Z", [late, fresh], ledger, tmp_path)
    assert hold.actions[0].kind == "wait" and "next look after 12 h" in hold.actions[0].reason
    # A capture that marks it finished: settle from it.
    finished = [dict(world_module.EVENTS[0], finished=True), *world_module.EVENTS[1:]]
    done = _capture(tmp_path / "s", "2026-08-25T09:00:00Z", events=finished)
    settle = _plan("2026-08-25T10:00:00Z", [late, fresh, done], ledger, tmp_path)
    kinds = [a.kind for a in settle.actions]
    assert kinds[0] == "settle" and settle.actions[0].snapshot_id == done.metadata.snapshot_id
    # And once settled, nothing about GW1 remains.
    after = _plan(
        "2026-08-25T10:00:00Z",
        [late, fresh, done],
        LedgerState(decided=frozenset({1}), settled=frozenset({1})),
        tmp_path,
    )
    assert all(a.gameweek != 1 for a in after.actions)


def test_a_capture_is_never_requested_twice_in_one_plan(tmp_path: Path) -> None:
    """Settle poll and deadline capture due together: one capture serves both."""

    late = _capture(tmp_path / "s", "2026-08-21T15:10:00Z")
    plan = _plan(
        "2026-08-28T15:30:00Z",
        [late],
        LedgerState(decided=frozenset({1})),
        tmp_path,
    )
    assert sum(1 for a in plan.actions if a.kind == "capture") == 1


def test_a_missed_deadline_is_named_and_not_decided_late(tmp_path: Path) -> None:
    late = _capture(tmp_path / "s", "2026-08-21T15:10:00Z")
    plan = _plan("2026-08-22T09:00:00Z", [late], LedgerState(), tmp_path)
    kinds = [a.kind for a in plan.actions]
    assert "decide" not in kinds
    assert any("missed" in a.reason and a.gameweek == 1 for a in plan.actions)
    assert plan.diagnostics["next_gameweek"] == 2


def test_timing_config_is_validated() -> None:
    with pytest.raises(Exception, match="positive"):
        TickConfig(capture_window_hours=0)


# --- runner ---------------------------------------------------------------------------


@pytest.fixture(name="world")
def _world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setattr(tick_script, "build_panel", lambda root: world_module._panel())
    # The world's handoff carries the really pinned in-season version; no monkeypatch,
    # so the runner exercises the real allowlist.
    state: dict[str, Any] = {
        "snapshot_root": tmp_path / "snapshots",
        "ledger_root": tmp_path / "ledger",
        "handoff_root": tmp_path / "handoffs",
        "summary": tmp_path / "docs" / "ledger.md",
        "clock": "2026-08-21T15:30:00Z",
        "captures": 0,
        "events": list(world_module.EVENTS),
        "elements": world_module._elements(),
    }

    def fake_capture(root: Path, *, dry_run: bool = False):
        state["captures"] += 1
        metadata = write_snapshot(
            root,
            source="fpl-live",
            captured_at_utc=state["clock"],
            payloads={
                BOOTSTRAP_PAYLOAD: world_module._bootstrap(
                    events=state["events"], elements=state["elements"]
                ),
                FIXTURES_PAYLOAD: b"[]",
            },
        )
        return metadata

    monkeypatch.setattr(tick_script, "capture_snapshot", fake_capture)
    return state


def _tick(monkeypatch: pytest.MonkeyPatch, world: dict[str, Any], *extra: str) -> int:
    argv = [
        "run_season_tick",
        "--snapshot-root",
        str(world["snapshot_root"]),
        "--ledger-root",
        str(world["ledger_root"]),
        "--handoff-root",
        str(world["handoff_root"]),
        "--summary-output",
        str(world["summary"]),
        "--log-root",
        str(world["summary"].parent / "logs"),
        "--now",
        world["clock"],
        *extra,
    ]
    monkeypatch.setattr("sys.argv", argv)
    return tick_script.main()


def test_the_runner_captures_and_decides_the_opening_gameweek_in_one_tick(
    monkeypatch: pytest.MonkeyPatch, world: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    assert _tick(monkeypatch, world) == 0
    out = capsys.readouterr().out
    assert world["captures"] == 1
    decision_path = world["ledger_root"] / SEASON / "gw01" / "decision.json"
    assert decision_path.is_file()
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    assert decision["metadata"]["mode"] == "live"
    assert "re-planned after capture" in out and "tick done: 2 action(s)" in out

    # The same tick again changes nothing.
    assert _tick(monkeypatch, world) == 0
    assert world["captures"] == 1
    assert "0 action(s)" in capsys.readouterr().out


def test_dry_run_prints_the_plan_and_changes_nothing(
    monkeypatch: pytest.MonkeyPatch, world: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    assert _tick(monkeypatch, world, "--dry-run") == 0
    out = capsys.readouterr().out
    assert "-> capture" in out and "dry run: nothing changed" in out
    assert world["captures"] == 0
    assert not world["ledger_root"].exists()


def test_the_runner_settles_after_the_gameweek_and_then_idles(
    monkeypatch: pytest.MonkeyPatch, world: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    assert _tick(monkeypatch, world) == 0  # GW1 captured and decided
    # Three days later the gameweek is finished and points are published.
    world["clock"] = "2026-08-24T18:00:00Z"
    world["events"] = [dict(world_module.EVENTS[0], finished=True), *world_module.EVENTS[1:]]
    world["elements"] = world_module._elements(event_points=3)
    assert _tick(monkeypatch, world) == 0
    outcome = world["ledger_root"] / SEASON / "gw01" / "outcome.json"
    assert outcome.is_file()
    assert json.loads(outcome.read_text(encoding="utf-8"))["realized_xi_score"] == 36.0
    assert world["captures"] == 2
    # Idle now: GW2 is days away.
    assert _tick(monkeypatch, world) == 0
    assert world["captures"] == 2
    assert "0 action(s)" in capsys.readouterr().out.split("tick at")[-1]


def test_the_runner_decides_the_second_gameweek_only_with_a_handoff(
    monkeypatch: pytest.MonkeyPatch, world: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    assert _tick(monkeypatch, world) == 0  # GW1
    world["clock"] = "2026-08-24T18:00:00Z"
    world["events"] = [dict(world_module.EVENTS[0], finished=True), *world_module.EVENTS[1:]]
    world["elements"] = world_module._elements(event_points=3)
    assert _tick(monkeypatch, world) == 0  # settle GW1
    # GW2 window, no handoff: capture, then wait and say where the handoff is expected.
    world["clock"] = "2026-08-28T15:00:00Z"
    world["elements"] = world_module._elements(event_points=3, price_shift={1001: 3})
    assert _tick(monkeypatch, world) == 0
    out = capsys.readouterr().out
    assert world["captures"] == 3
    assert "no projection handoff at" in out
    assert not (world["ledger_root"] / SEASON / "gw02").exists()
    # The producer drops the handoff for this capture; the next tick decides.
    snapshot_ids = sorted((world["snapshot_root"]).iterdir())
    latest_id = snapshot_ids[-1].name
    from squadopt.live import InSeasonProjection, write_projection_handoff

    expected: dict[int, float] = {}
    code = 1000
    for _, count in world_module.SHAPE:
        for _ in range(count):
            code += 1
            expected[code] = 2.0 + (code % 3) * 0.5
    write_projection_handoff(
        handoff_path_for(world["handoff_root"], SEASON, 2),
        InSeasonProjection(
            season=SEASON,
            gameweek=2,
            source_snapshot_id=latest_id,
            model_name=CONTROL_MODEL_NAME,
            model_version=world_module.IN_SEASON_VERSION,
            feature_contract_version="synthetic-in-season-features-v0",
            expected_points=expected,
        ),
    )
    world["clock"] = "2026-08-28T16:00:00Z"
    assert _tick(monkeypatch, world) == 0
    assert world["captures"] == 3  # the window capture is reused, not retaken
    decision = json.loads(
        (world["ledger_root"] / SEASON / "gw02" / "decision.json").read_text(encoding="utf-8")
    )
    assert decision["transfers"]["previous_gameweek"] == 1

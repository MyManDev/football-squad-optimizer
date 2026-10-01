"""The policy chain's runner applies its protocol: the capture, the arms, the carry and the records.

Synthetic and offline throughout. The runner is held to
``docs/research/planner_policy_chain_prereg.md``; each test names the rule it pins.
"""

from __future__ import annotations

import json
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
from scripts import measure_planner_policy_chain as chain
from tests.unit.test_football_prospective_prereg import _artifact
from tests.unit.test_live_horizon_planning import _inputs
from tests.unit.test_live_recommendation import _bootstrap, _capture
from tests.unit.test_live_transfers import CHIPS, _game_config

from squadopt.application.weekly_suggestion_eval import score_recorded_advice
from squadopt.data.atomic import write_document_once
from squadopt.data.errors import ConflictingBytesError
from squadopt.live import plan_transfer_horizon
from squadopt.live import transfers as live_transfers
from squadopt.live.football_artifact import football_artifact_path
from squadopt.live.recommendation import read_inputs
from squadopt.optimization import OptimizationConfig
from squadopt.planning import PlanningHorizon
from squadopt.planning.optimizer import optimize_transfer_plan
from squadopt.planning.pricing import sell_price_tenths

PROTOCOL_TEXT = " ".join(chain.PROTOCOL_PATH.read_text(encoding="utf-8").split())
T0 = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
BUDGET = OptimizationConfig(solver_time_limit_seconds=300, solver_deterministic_time_limit=20)


def _entry(snapshot: str, hours: float, target: int | None) -> chain.CaptureIndexEntry:
    return chain.CaptureIndexEntry(snapshot, T0 + timedelta(hours=hours), target)


# Rule 4: the decision capture


def test_the_decision_capture_is_the_latest_capture_whose_own_target_is_the_week() -> None:
    index = (
        _entry("early", 0, 6),
        _entry("latest-own", 5, 6),
        _entry("previous-target", 9, 5),
        _entry("unreadable", 10, None),
    )
    assert chain.decision_capture(index, 6) == chain.Selection("latest-own", None)


def test_two_captures_at_the_latest_instant_make_the_week_missing() -> None:
    index = (_entry("a", 3, 6), _entry("b", 3, 6), _entry("older", 1, 6))
    assert chain.decision_capture(index, 6) == chain.Selection(None, "tied_latest_captures")


def test_a_capture_that_targets_the_previous_week_is_never_this_weeks() -> None:
    index = (_entry("last-weeks", 2, 5),)
    assert chain.decision_capture(index, 6) == chain.Selection(None, "no_own_target_capture")


# Rule 5: the served forecast, read and never rebuilt


def _served(tmp_path: Path, *, written_before_deadline: bool = True) -> tuple[Path, Path, str]:
    """A synthetic capture with its served v1 artifact, written at a chosen instant."""

    snapshots = tmp_path / "snapshots"
    bootstrap = json.loads(_bootstrap().decode("utf-8"))
    bootstrap["game_config"] = _game_config()
    bootstrap["chips"] = CHIPS
    capture = _capture(snapshots, bootstrap=json.dumps(bootstrap).encode("utf-8"))
    inputs = read_inputs(capture, season=chain.SEASON)
    artifacts = tmp_path / "artifacts"
    path = football_artifact_path(artifacts, capture.metadata.snapshot_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_artifact(inputs)), encoding="utf-8")
    deadline = chain._instant(inputs.deadline.deadline_utc)
    written = deadline + (timedelta(hours=-1) if written_before_deadline else timedelta(0))
    os.utime(path, (written.timestamp(), written.timestamp()))
    return snapshots, artifacts, capture.metadata.snapshot_id


def test_a_served_forecast_written_before_the_deadline_is_read(tmp_path: Path) -> None:
    snapshots, artifacts, snapshot_id = _served(tmp_path)
    week = chain.week_inputs(snapshots, artifacts, snapshot_id)
    assert isinstance(week, chain.WeekInputs)
    assert week.inputs.snapshot_id == snapshot_id
    assert len(week.artifact_sha256) == 64


def test_a_capture_without_its_served_forecast_is_a_missing_week(tmp_path: Path) -> None:
    snapshots, artifacts, snapshot_id = _served(tmp_path)
    football_artifact_path(artifacts, snapshot_id).unlink()
    assert chain.week_inputs(snapshots, artifacts, snapshot_id) == "no_artifact"


def test_a_forecast_written_at_the_deadline_is_a_missing_week(tmp_path: Path) -> None:
    snapshots, artifacts, snapshot_id = _served(tmp_path, written_before_deadline=False)
    reason = chain.week_inputs(snapshots, artifacts, snapshot_id)
    assert reason == "artifact_written_at_or_after_deadline"


def test_a_forecast_that_fails_its_fingerprint_is_a_missing_week(tmp_path: Path) -> None:
    snapshots, artifacts, snapshot_id = _served(tmp_path)
    path = football_artifact_path(artifacts, snapshot_id)
    stamp = path.stat().st_mtime
    document = json.loads(path.read_text(encoding="utf-8"))
    document["rows"][0]["expected_points"] = float(document["rows"][0]["expected_points"]) + 1.0
    path.write_text(json.dumps(document), encoding="utf-8")
    os.utime(path, (stamp, stamp))
    reason = chain.week_inputs(snapshots, artifacts, snapshot_id)
    assert reason == "artifact_unreadable_or_unbound"


# Rules 10 and 11: the hold arm is the standard path, plan for plan


@pytest.mark.parametrize("length", [3, 5])
def test_the_hold_arm_is_the_standard_path_plan_for_plan(tmp_path: Path, length: int) -> None:
    """A control-model horizon takes the standard path, so the two must agree exactly."""

    inputs, horizon, held, rules = _inputs(tmp_path, tuple(range(2, 2 + length)))
    served, served_policy = plan_transfer_horizon(
        inputs, horizon, held, rules, optimization=BUDGET, linearization_level=2
    )
    prepared = chain.prepare_window(inputs, horizon, held, rules)
    ours = optimize_transfer_plan(
        PlanningHorizon(prepared.planning_table),
        prepared.state,
        BUDGET,
        prepared.policy,
        linearization_level=2,
        protect_hold=True,
    )
    assert prepared.policy.configuration_fingerprint == served_policy.configuration_fingerprint
    assert ours.solver_status == served.solver_status
    assert ours.objective_value == served.objective_value
    for mine, theirs in zip(ours.weeks, served.weeks, strict=True):
        assert sorted(mine.selected_squad.player_id) == sorted(theirs.selected_squad.player_id)
        assert sorted(mine.transfers_in.player_id) == sorted(theirs.transfers_in.player_id)
        assert mine.bank_after_tenths == theirs.bank_after_tenths
        assert int(mine.captain["player_id"]) == int(theirs.captain["player_id"])


def test_the_hold_arm_refuses_a_horizon_from_another_capture(tmp_path: Path) -> None:
    inputs, horizon, held, rules = _inputs(tmp_path, (2, 3, 4))
    with pytest.raises(chain.ChainError):
        chain.prepare_window(replace(inputs, snapshot_id="another-capture"), horizon, held, rules)


# Rule 15: the carry is the ledger's carry


def test_the_state_after_a_week_is_the_ledgers_state_after_it(tmp_path: Path) -> None:
    inputs, horizon, held, rules = _inputs(tmp_path, (2, 3, 4))
    plan, policy = plan_transfer_horizon(
        inputs, horizon, held, rules, optimization=BUDGET, linearization_level=2
    )
    first = horizon.table.loc[horizon.table.gameweek == 2]
    current = {int(p): int(c) for p, c in zip(first.player_id, first.price_tenths, strict=True)}
    fee = float(rules.transfers.sell_on_fee)
    sells = {
        p: sell_price_tenths(current[p], held.purchase_prices[p], sell_on_fee=fee)
        for p in held.squad_player_ids
    }
    ledger = live_transfers._package_decision(plan, held, None, policy, sells, current, fee)
    state = chain.ChainState(
        held.squad_player_ids,
        dict(held.purchase_prices),
        held.bank_tenths,
        held.free_transfers,
        held.decided_gameweek,
    )
    after = chain.advance(state, plan.weeks[0], current, fee)
    assert dict(after.purchase_prices) == dict(ledger.purchase_prices_after)
    assert after.bank_tenths == ledger.bank_after_tenths
    assert after.free_transfers == ledger.free_transfers_after
    assert after.decided_gameweek == 2


def test_a_plan_whose_bank_does_not_follow_from_its_moves_is_refused(tmp_path: Path) -> None:
    inputs, horizon, held, rules = _inputs(tmp_path, (2, 3, 4))
    plan, _ = plan_transfer_horizon(
        inputs, horizon, held, rules, optimization=BUDGET, linearization_level=2
    )
    first = horizon.table.loc[horizon.table.gameweek == 2]
    current = {int(p): int(c) for p, c in zip(first.player_id, first.price_tenths, strict=True)}
    state = chain.ChainState(
        held.squad_player_ids,
        dict(held.purchase_prices),
        held.bank_tenths + 1,
        held.free_transfers,
        held.decided_gameweek,
    )
    with pytest.raises(chain.ChainError):
        chain.advance(state, plan.weeks[0], current, float(rules.transfers.sell_on_fee))


# Rules 18 and 19: a missing week or a failed arm holds


@pytest.mark.parametrize(("before", "cap", "expected"), [(1, 5, 2), (5, 5, 5), (0, 2, 1)])
def test_a_held_week_banks_one_free_transfer_up_to_the_captured_maximum(
    before: int, cap: int, expected: int
) -> None:
    state = chain.ChainState((1, 2), {1: 50, 2: 60}, 7, before, 5)
    held = chain.hold(state, 6, cap)
    assert (held.free_transfers, held.decided_gameweek) == (expected, 6)
    assert (held.squad, dict(held.purchase_prices), held.bank_tenths) == ((1, 2), {1: 50, 2: 60}, 7)


# Rule 11: the window and its truncation


def test_a_window_is_truncated_at_the_seasons_end() -> None:
    assert chain.window_weeks("served_5", 6) == (6, 7, 8, 9, 10)
    assert chain.window_weeks("hold_3", 37) == (37, 38)
    assert chain.window_weeks("served_5", 38) == (38,)


def test_the_served_route_is_read_from_the_plans_own_diagnostics() -> None:
    def plan(diagnostics: dict[str, object]) -> object:
        return type("Plan", (), {"diagnostics": diagnostics})()

    observed = plan({"observed_window": {"version": "bounded_observed_window_v1"}})
    guarded = plan({"sequential_incumbent": {"version": "sequential_certified_window_v1"}})
    assert chain._route(observed) == ("observed", "bounded_observed_window_v1")  # type: ignore[arg-type]
    assert chain._route(guarded) == ("guarded", "sequential_certified_window_v1")  # type: ignore[arg-type]
    assert chain._route(plan({})) == ("standard", None)  # type: ignore[arg-type]


# Rules 16 and 23: the lineup is one the scorer accepts


def test_the_recorded_lineup_is_one_the_scorer_accepts(tmp_path: Path) -> None:
    inputs, horizon, held, rules = _inputs(tmp_path, (2, 3, 4))
    plan, _ = plan_transfer_horizon(
        inputs, horizon, held, rules, optimization=BUDGET, linearization_level=2
    )
    week = plan.weeks[0]
    advice = chain.scoring_block(week)
    squad = [int(p) for p in week.selected_squad.player_id]
    record = {"players": chain.players_block(horizon.table.loc[horizon.table.gameweek == 2], squad)}
    outcomes = pd.DataFrame({"player_id": squad, "total_points": [2] * 15, "minutes": [90] * 15})
    scored, players = score_recorded_advice(record, advice, outcomes)
    assert len(players) == 15
    assert advice["transfer_hit_points"] == float(week.transfer_hit_points)
    assert scored is not None


# Rule 21: records are written once, and work is outside what two writes must agree on


def test_a_record_replays_despite_its_work_and_refuses_a_different_decision(tmp_path: Path) -> None:
    path = tmp_path / "p1000-served_3.json"
    first = {"status": "decided", "plan": {"captain": 7}, "work": {"deterministic_time_used": 1.0}}
    write_document_once(first, path, replay_identity=chain.replay_identity)
    again = {**first, "work": {"deterministic_time_used": 1.0000000000000002}}
    write_document_once(again, path, replay_identity=chain.replay_identity)
    assert json.loads(path.read_text(encoding="utf-8"))["work"] == first["work"]
    with pytest.raises(ConflictingBytesError):
        write_document_once(
            {**first, "plan": {"captain": 8}}, path, replay_identity=chain.replay_identity
        )


# Rules 3 and 34: the frozen source and where the chain may write


def test_a_later_run_from_another_source_is_refused(tmp_path: Path) -> None:
    identity = {"protocol": chain.PROTOCOL_ID, "repository_commit": "aaaa", "versions": {}}
    assert chain.bind_protocol(tmp_path, identity, 6) == 6
    assert chain.bind_protocol(tmp_path, identity, 7) == 6
    with pytest.raises(chain.ChainError):
        chain.bind_protocol(tmp_path, {**identity, "repository_commit": "bbbb"}, 6)


def test_the_chain_never_writes_under_data_or_a_football_artifact_root(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    with pytest.raises(chain.ChainError):
        chain.refuse_output(chain.REPOSITORY / "data" / "chain", artifacts)
    with pytest.raises(chain.ChainError):
        chain.refuse_output(artifacts / "football" / "chain", artifacts)
    chain.refuse_output(tmp_path / "chain", artifacts)


# Rules 7 and 33: what the runner never reads or records


def test_the_runner_reads_no_outcome_and_records_no_member() -> None:
    source = chain.RUNNER_PATH.read_text(encoding="utf-8")
    for name in ("live_event_outcomes", "score_recorded_advice", "weekly_suggestion_eval"):
        assert name not in source
    for name in ("entry_id", "league_id", "data/entries", "archive_history"):
        assert name not in source


# Rules 8 and 10: the runner's constants are the protocol's


def test_the_runners_constants_are_the_protocols() -> None:
    assert chain.PROFILES == ((1000, 1000, 1), (950, 1000, 2), (900, 900, 0))
    assert chain.ARMS == ("served_3", "served_5", "hold_3", "hold_5", "one_week")
    assert chain.UNITS_PER_WEEK == 20.0
    assert chain.HOLD_PROBE_UNITS == 1.0
    assert chain.SQUAD_CONFIG.bench_weight == 0
    assert chain.SQUAD_CONFIG.solver_time_limit_seconds == 120
    assert chain.SQUAD_CONFIG.solver_deterministic_time_limit == 60
    matrix = chain.REPOSITORY / "scripts" / "measure_shortlist_matrix.py"
    assert "(1000, 1000, 1), (950, 1000, 2), (900, 900, 0)" in matrix.read_text(encoding="utf-8")
    for phrase in (
        "squad budgets of 1000, 950 and 900 tenths",
        "total funds of 1000, 1000 and 900",
        "one, two and zero free transfers",
        "59 and 99, plus the 1-unit hold probe",
        "at twenty deterministic units per forecast week",
    ):
        assert phrase in PROTOCOL_TEXT

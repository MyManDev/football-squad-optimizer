"""Integration tests for planning from a captured multi-gameweek projection."""

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from tests.unit.test_live_recommendation import (
    GW1_REPLAY_SQUAD,
    GW1_REPLAY_TOTAL_COST_TENTHS,
    SEASON,
)
from tests.unit.test_live_recommendation import (
    _bootstrap as _projection_bootstrap,
)
from tests.unit.test_live_transfers import CHIPS, _game_config
from tests.unit.test_projection_horizon_builder import (
    _calendar,
    _capture,
    _in_season_handoff,
)

from squadopt.application import horizon_plan_document, write_horizon_plan
from squadopt.application import horizon_plans as horizon_service
from squadopt.data.errors import DataError, DataSourceError
from squadopt.live import (
    HeldSquad,
    build_projection_horizon,
    plan_transfer_horizon,
    read_inputs,
    read_season_rules,
)
from squadopt.live import transfers as live_transfers
from squadopt.optimization import SolverStatus
from squadopt.planning import (
    FirstWeekOverlap,
    ProjectionHorizon,
    TransferPlanningValidationError,
)


def _held(players: pd.DataFrame) -> HeldSquad:
    prices = {
        int(player): int(price)
        for player, price in zip(
            players["player_id"].tolist(), players["price_tenths"].tolist(), strict=True
        )
    }
    purchase = {player: prices[player] for player in GW1_REPLAY_SQUAD}
    return HeldSquad(
        season=SEASON,
        decided_gameweek=1,
        squad_player_ids=GW1_REPLAY_SQUAD,
        purchase_prices=purchase,
        bank_tenths=1_000 - GW1_REPLAY_TOTAL_COST_TENTHS,
        free_transfers=1,
        chips_used={},
    )


def _inputs(tmp_path: Path, gameweeks: tuple[int, ...]) -> tuple[object, ...]:
    bootstrap = json.loads(_projection_bootstrap().decode("utf-8"))
    deadlines = {
        3: "2026-09-12T17:30:00Z",
        4: "2026-09-19T17:30:00Z",
        5: "2026-09-26T17:30:00Z",
        6: "2026-10-03T17:30:00Z",
    }
    for gameweek in range(3, max(gameweeks) + 1):
        bootstrap["events"].append(
            {
                "id": gameweek,
                "deadline_time": deadlines[gameweek],
                "finished": False,
            }
        )
    bootstrap["game_config"] = _game_config()
    bootstrap["chips"] = CHIPS
    capture = _capture(
        tmp_path,
        bootstrap=json.dumps(bootstrap).encode("utf-8"),
        fixtures=_calendar(gameweeks=tuple(range(1, max(gameweeks) + 1))),
    )
    inputs = read_inputs(capture, season=SEASON, gameweek=2)
    horizon = build_projection_horizon(
        capture,
        gameweeks,
        season=SEASON,
        in_season=_in_season_handoff(capture),
    )
    return inputs, horizon, _held(inputs.players), read_season_rules(capture, season=SEASON)


@pytest.mark.parametrize("length", [1, 3])
def test_live_horizon_plans_every_requested_gameweek(tmp_path: Path, length: int) -> None:
    gameweeks = tuple(range(2, 2 + length))
    inputs, horizon, held, rules = _inputs(tmp_path, gameweeks)

    plan, config = plan_transfer_horizon(inputs, horizon, held, rules)

    assert plan.solver_status is SolverStatus.OPTIMAL
    assert tuple(week.gameweek for week in plan.weeks) == gameweeks
    assert plan.diagnostics["horizon_length"] == length
    assert config.max_free_transfers == rules.transfers.max_free_transfers
    assert config.max_transfers_per_gameweek == (None if length == 1 else 1)


@pytest.mark.parametrize("length", [1, 3, 5])
def test_the_horizon_path_plans_under_the_same_policy_as_the_one_week_path(
    tmp_path: Path, length: int
) -> None:
    """One policy for both member paths, or a window prices a hit differently from a week.

    ``plan_transfer_horizon`` used to spell its controls out, which coincided with the
    dataclass defaults and so hid the bug: the moment ``MEMBER_PLANNING_POLICY`` moves off
    those defaults, a member's three- or five-week window would plan at one hit cost and
    their one-week advice at another. Both build from the policy now, and both report the
    hits at the game's charge whatever the planner was told to pay.
    """

    gameweeks = tuple(range(2, 2 + length))
    inputs, horizon, held, rules = _inputs(tmp_path, gameweeks)

    plan, config = plan_transfer_horizon(inputs, horizon, held, rules)

    expected = live_transfers._transfer_config(rules, transfer_cap=None if length == 1 else 1)
    assert config.configuration_fingerprint == expected.configuration_fingerprint
    assert (
        config.transfer_hit_cost_points
        == (live_transfers.MEMBER_PLANNING_POLICY["transfer_hit_cost_points"])
    )
    charged = live_transfers.MEMBER_PLANNING_POLICY["hit_points_charged"]
    assert config.hit_points_charged == charged
    for week in plan.weeks:
        assert week.transfer_hit_points == week.paid_transfer_count * float(str(charged))
    assert plan.total_transfer_hit_points == sum(week.transfer_hit_points for week in plan.weeks)


def test_the_same_live_horizon_plans_identically_twice(tmp_path: Path) -> None:
    inputs, horizon, held, rules = _inputs(tmp_path, (2,))

    first, _ = plan_transfer_horizon(inputs, horizon, held, rules)
    second, _ = plan_transfer_horizon(inputs, horizon, held, rules)

    assert first.objective_value == second.objective_value
    assert_frame_equal(first.weeks[0].selected_squad, second.weeks[0].selected_squad)
    assert_frame_equal(first.weeks[0].starting_xi, second.weeks[0].starting_xi)
    assert first.weeks[0].captain["player_id"] == second.weeks[0].captain["player_id"]


def test_a_horizon_from_another_snapshot_is_refused(tmp_path: Path) -> None:
    inputs, horizon, held, rules = _inputs(tmp_path, (2,))
    mismatched = replace(horizon, source_snapshot_id="another-capture")

    with pytest.raises(DataSourceError, match="snapshot"):
        plan_transfer_horizon(inputs, mismatched, held, rules)


def test_unversioned_price_changes_are_refused(tmp_path: Path) -> None:
    inputs, horizon, held, rules = _inputs(tmp_path, (2, 3))
    changed = horizon.table.copy(deep=True)
    player = changed.iloc[0]["player_id"]
    changed.loc[
        (changed["gameweek"] == 3) & (changed["player_id"] == player),
        "price_tenths",
    ] += 1
    changing_horizon = ProjectionHorizon(
        table=changed,
        season=horizon.season,
        source_snapshot_id=horizon.source_snapshot_id,
        model_name=horizon.model_name,
        model_version=horizon.model_version,
        feature_contract_version=horizon.feature_contract_version,
        post_processing_contract_version=horizon.post_processing_contract_version,
    )

    with pytest.raises(DataSourceError, match="price-transition model"):
        plan_transfer_horizon(inputs, changing_horizon, held, rules)


def test_planning_does_not_mutate_the_projection_horizon(tmp_path: Path) -> None:
    inputs, horizon, held, rules = _inputs(tmp_path, (2,))
    before = horizon.table.copy(deep=True)

    plan_transfer_horizon(inputs, horizon, held, rules)

    assert_frame_equal(horizon.table, before)


def test_the_operational_document_is_structured_and_contains_no_percentage_claim(
    tmp_path: Path,
) -> None:
    inputs, horizon, held, rules = _inputs(tmp_path, (2,))
    plan, config = plan_transfer_horizon(inputs, horizon, held, rules)

    document = horizon_plan_document(
        horizon,
        plan,
        config,
        projection_handoff_fingerprint="handoff-fingerprint",
        initial_state_fingerprint="initial-state-fingerprint",
    )
    encoded = json.dumps(document, sort_keys=True)

    assert document["solver_status"] == "OPTIMAL"
    assert document["target_gameweeks"] == [2]
    assert len(document["weeks"]) == 1
    assert len(str(document["artifact_fingerprint"])) == 64
    assert {
        "solve_time_seconds",
        "deterministic_time_used",
        "tiebreak_deterministic_time",
        "tiebreak_deterministic_time_limit",
    }.isdisjoint(document["diagnostics"])
    nudged = replace(
        plan,
        diagnostics={
            **dict(plan.diagnostics),
            "solve_time_seconds": 99.0,
            "deterministic_time_used": 0.015177973877980358,
            "tiebreak_deterministic_time": 0.008758917086667175,
            "tiebreak_deterministic_time_limit": 59.993580943208684,
        },
    )
    assert (
        horizon_plan_document(
            horizon,
            nudged,
            config,
            projection_handoff_fingerprint="handoff-fingerprint",
            initial_state_fingerprint="initial-state-fingerprint",
        )
        == document
    )
    assert "%" not in encoded


def test_a_deterministically_truncated_plan_remains_structured_shadow_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs, horizon, held, rules = _inputs(tmp_path, (2,))
    proven, _ = plan_transfer_horizon(inputs, horizon, held, rules)
    feasible = replace(
        proven,
        solver_status=SolverStatus.FEASIBLE,
        diagnostics={**dict(proven.diagnostics), "relative_optimality_gap": 0.05},
    )
    monkeypatch.setattr(
        live_transfers, "optimize_transfer_plan", lambda *_args, **_kwargs: feasible
    )

    plan, config = plan_transfer_horizon(inputs, horizon, held, rules)
    document = horizon_plan_document(
        horizon,
        plan,
        config,
        projection_handoff_fingerprint="handoff-fingerprint",
        initial_state_fingerprint="initial-state-fingerprint",
    )

    assert plan.solver_status is SolverStatus.FEASIBLE
    assert document["publication_status"] == "shadow_only"
    assert document["solver_proof_status"] == "unproven"


def test_an_optimal_long_horizon_remains_research_shadow(tmp_path: Path) -> None:
    inputs, horizon, held, rules = _inputs(tmp_path, (2, 3, 4))
    plan, config = plan_transfer_horizon(inputs, horizon, held, rules)

    document = horizon_plan_document(
        horizon,
        plan,
        config,
        projection_handoff_fingerprint="handoff-fingerprint",
        initial_state_fingerprint="initial-state-fingerprint",
    )

    assert document["solver_proof_status"] == "proven"
    assert document["decision_role"] == "research_shadow"
    assert document["publication_status"] == "shadow_only"


def test_chips_are_offered_only_when_the_caller_names_them(tmp_path: Path) -> None:
    """The bridge plays no chip by itself; a caller who names the availability gets a
    plan that spends each offered chip at most once inside the horizon."""

    from squadopt.live import chip_availability_for

    inputs, horizon, held, rules = _inputs(tmp_path, (2, 3, 4))
    silent, _ = plan_transfer_horizon(inputs, horizon, held, rules)
    assert dict(silent.chips_played) == {}
    assert all(week.chip is None for week in silent.weeks)

    offered = chip_availability_for(rules, (2, 3, 4), used=held.chips_used)
    assert "bboost" in offered.available
    plan, _ = plan_transfer_horizon(inputs, horizon, held, rules, chips=offered)
    played = dict(plan.chips_played)
    assert set(played) <= {2, 3, 4}
    assert len(set(played.values())) == len(played)
    for gameweek, name in played.items():
        assert gameweek in offered.gameweeks_for(name)


def test_planner_refuses_a_horizon_mutated_after_fingerprinting(tmp_path: Path) -> None:
    inputs, horizon, held, rules = _inputs(tmp_path, (2,))
    horizon.table.loc[horizon.table.index[0], "expected_points"] += 1.0

    with pytest.raises(TransferPlanningValidationError, match="changed after its fingerprint"):
        plan_transfer_horizon(inputs, horizon, held, rules)


def test_an_identical_replay_is_a_no_op_and_different_content_is_refused(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "plan.json"
    document: dict[str, object] = {"contract_version": "test_v1", "value": 1}

    assert write_horizon_plan(destination, document) is True
    original = destination.read_bytes()
    assert write_horizon_plan(destination, document) is False
    assert destination.read_bytes() == original
    assert not list(tmp_path.glob(".*.tmp"))

    with pytest.raises(DataError, match="Refusing to overwrite"):
        write_horizon_plan(destination, {**document, "value": 2})


def test_a_failure_before_publication_leaves_no_final_or_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "plan.json"

    def fail_durability(_file_descriptor: int) -> None:
        raise OSError("synthetic durability failure")

    monkeypatch.setattr(horizon_service.os, "fsync", fail_durability)

    with pytest.raises(OSError, match="synthetic durability failure"):
        write_horizon_plan(destination, {"contract_version": "test_v1"})
    assert not destination.exists()
    assert not list(tmp_path.glob(".plan.json.*.tmp"))


def test_concurrent_identical_writers_publish_once_and_replay_the_same_bytes(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "plan.json"
    document: dict[str, object] = {"contract_version": "test_v1", "value": 1}

    with ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = list(
            executor.map(lambda _index: write_horizon_plan(destination, document), range(8))
        )

    assert outcomes.count(True) == 1
    assert outcomes.count(False) == 7
    assert json.loads(destination.read_text(encoding="utf-8")) == document
    assert not list(tmp_path.glob(".plan.json.*.tmp"))


def test_the_horizon_path_passes_a_band_and_a_first_week_cap_to_the_planner(
    tmp_path: Path,
) -> None:
    """Both seams reach the solver, and neither is on by default.

    A rival-strategy band constrains the decided week; the cap keeps the later weeks
    from being charged for it without uncapping them. They are handed straight through,
    so what has to be shown here is that they arrive and that a caller naming neither
    gets the planner it had.
    """

    inputs, horizon, held, rules = _inputs(tmp_path, (2, 3, 4))
    # The default policy already caps every week of a multi-week horizon at one, so the
    # first-week cap is only observable against a policy that caps no week.
    uncapped = live_transfers._transfer_config(rules, transfer_cap=None)
    band_players = frozenset(int(player) for player in held.squad_player_ids[:8])
    band = FirstWeekOverlap(player_ids=band_players, minimum=8)

    silent, _ = plan_transfer_horizon(inputs, horizon, held, rules, transfer_config=uncapped)
    assert silent.diagnostics["first_week_overlap"] is None
    assert silent.diagnostics["first_week_transfer_cap"] is None

    plan, config = plan_transfer_horizon(
        inputs,
        horizon,
        held,
        rules,
        transfer_config=uncapped,
        first_week_overlap=band,
        first_week_transfer_cap=1,
    )

    assert plan.diagnostics["first_week_overlap"] == {
        "player_count": 8,
        "minimum": 8,
        "maximum": None,
    }
    assert plan.diagnostics["first_week_transfer_cap"] == 1
    held_first_week = {int(value) for value in plan.weeks[0].selected_squad["player_id"].tolist()}
    assert len(held_first_week & band_players) >= 8
    assert all(week.transfer_count <= 1 for week in plan.weeks[1:])
    # The cap is not a configuration control, so the digest the ledger records for this
    # plan is the digest of the policy the caller handed in, unchanged.
    assert config.configuration_fingerprint == uncapped.configuration_fingerprint
    assert config.max_transfers_per_gameweek is None

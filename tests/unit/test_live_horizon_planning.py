"""Integration tests for planning from a captured multi-gameweek projection."""

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from scripts import plan_transfer_horizon as horizon_cli
from scripts.plan_transfer_horizon import _document, _write_once
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
    _capture,
    _in_season_handoff,
)

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
from squadopt.planning import ProjectionHorizon


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
    bootstrap["game_config"] = _game_config()
    bootstrap["chips"] = CHIPS
    capture = _capture(tmp_path, bootstrap=json.dumps(bootstrap).encode("utf-8"))
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
    assert config.max_transfers_per_gameweek == 1


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

    document = _document(horizon, plan, config)
    encoded = json.dumps(document, sort_keys=True)

    assert document["solver_status"] == "OPTIMAL"
    assert document["target_gameweeks"] == [2]
    assert len(document["weeks"]) == 1
    assert len(str(document["artifact_fingerprint"])) == 64
    assert "solve_time_seconds" not in document["diagnostics"]
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
    document = _document(horizon, plan, config)

    assert plan.solver_status is SolverStatus.FEASIBLE
    assert document["publication_status"] == "shadow_unproven"


def test_an_identical_replay_is_a_no_op_and_different_content_is_refused(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "plan.json"
    document: dict[str, object] = {"contract_version": "test_v1", "value": 1}

    assert _write_once(destination, document) is True
    original = destination.read_bytes()
    assert _write_once(destination, document) is False
    assert destination.read_bytes() == original

    with pytest.raises(DataError, match="Refusing to overwrite"):
        _write_once(destination, {**document, "value": 2})


def test_a_failure_before_publication_leaves_no_final_or_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "plan.json"

    def fail_durability(_file_descriptor: int) -> None:
        raise OSError("synthetic durability failure")

    monkeypatch.setattr(horizon_cli.os, "fsync", fail_durability)

    with pytest.raises(OSError, match="synthetic durability failure"):
        _write_once(destination, {"contract_version": "test_v1"})
    assert not destination.exists()
    assert not list(tmp_path.glob(".plan.json.*.tmp"))


def test_concurrent_identical_writers_publish_once_and_replay_the_same_bytes(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "plan.json"
    document: dict[str, object] = {"contract_version": "test_v1", "value": 1}

    with ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = list(executor.map(lambda _index: _write_once(destination, document), range(8)))

    assert outcomes.count(True) == 1
    assert outcomes.count(False) == 7
    assert json.loads(destination.read_text(encoding="utf-8")) == document
    assert not list(tmp_path.glob(".plan.json.*.tmp"))

"""Application-level E2E checks for an in-season transfer horizon."""

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
import scripts.plan_transfer_horizon as horizon_cli
import tests.unit.test_live_transfers as transfer_world
from tests.unit.test_projection_horizon_builder import _calendar

import squadopt.application.horizon_plans as horizon_service
from squadopt.application import (
    DecideRequest,
    HorizonPlanRequest,
    HorizonPlanResult,
    decide,
    plan_horizon,
)
from squadopt.data.errors import DataError
from squadopt.data.snapshots import write_snapshot
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD
from squadopt.optimization import SolverStatus
from squadopt.planning import TransferPlanningConfig, TransferPlanResult


def _world(tmp_path: Path) -> dict[str, Any]:
    snapshot_root = tmp_path / "snapshots"
    opening = write_snapshot(
        snapshot_root,
        source="fpl-live",
        captured_at_utc=transfer_world.GW1_CAPTURED_AT,
        payloads={
            BOOTSTRAP_PAYLOAD: transfer_world._bootstrap(),
            FIXTURES_PAYLOAD: _calendar(),
        },
    )
    events = [
        dict(transfer_world.EVENTS[0], finished=True),
        transfer_world.EVENTS[1],
        transfer_world.EVENTS[2],
        {"id": 4, "deadline_time": "2026-09-19T17:30:00Z", "finished": False},
        {"id": 5, "deadline_time": "2026-09-26T17:30:00Z", "finished": False},
        {"id": 6, "deadline_time": "2026-10-03T17:30:00Z", "finished": False},
    ]
    deadline = write_snapshot(
        snapshot_root,
        source="fpl-live",
        captured_at_utc=transfer_world.GW2_CAPTURED_AT,
        payloads={
            BOOTSTRAP_PAYLOAD: transfer_world._bootstrap(
                events=events,
                elements=transfer_world._elements(
                    event_points=2,
                    price_shift={1001: 3, 1012: 1, 1020: -2},
                    injured=(1005,),
                ),
            ),
            FIXTURES_PAYLOAD: _calendar(gameweeks=(1, 2, 3, 4, 5, 6)),
        },
    )
    world = {
        "snapshot_root": snapshot_root,
        "ledger_root": tmp_path / "ledger",
        "handoffs": tmp_path / "handoffs",
        "gw1_id": opening.snapshot_id,
        "gw2_id": deadline.snapshot_id,
    }
    decide(
        DecideRequest(
            snapshot_root=snapshot_root,
            snapshot_id=opening.snapshot_id,
            ledger_root=world["ledger_root"],
            archive_root=tmp_path / "archive",
        ),
        panel_builder=lambda _root: transfer_world._panel(),
    )
    world["handoff"] = transfer_world._handoff(world)
    return world


def _request(world: dict[str, Any], tmp_path: Path) -> HorizonPlanRequest:
    return HorizonPlanRequest(
        snapshot_root=world["snapshot_root"],
        snapshot_id=world["gw2_id"],
        ledger_root=world["ledger_root"],
        artifact_root=tmp_path / "artifacts" / "live",
        in_season_projection=world["handoff"],
        gameweeks=1,
    )


def test_plan_horizon_returns_a_structured_replay_safe_result(tmp_path: Path) -> None:
    world = _world(tmp_path)
    request = _request(world, tmp_path)

    first = plan_horizon(request)
    second = plan_horizon(request)

    assert isinstance(first, HorizonPlanResult)
    assert first.solver_status is SolverStatus.OPTIMAL
    assert first.publication_status == "decision_eligible"
    assert first.document["decision_role"] == "live_control"
    assert first.document["solver_proof_status"] == "proven"
    assert (first.first_gameweek, first.last_gameweek) == (2, 2)
    assert first.created is True and second.created is False
    assert first.artifact_path == second.artifact_path
    assert first.artifact_path.is_file()
    assert first.artifact_fingerprint == second.artifact_fingerprint
    assert first.document == second.document


def test_cli_is_a_thin_adapter_over_the_application_operation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    world = _world(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        [
            "plan_transfer_horizon",
            "--snapshot-root",
            str(world["snapshot_root"]),
            "--ledger-root",
            str(world["ledger_root"]),
            "--snapshot-id",
            str(world["gw2_id"]),
            "--in-season-projection",
            str(world["handoff"]),
            "--artifact-root",
            str(tmp_path / "artifacts" / "live"),
            "--gameweeks",
            "1",
        ],
    )

    assert horizon_cli.main() == 0
    output = capsys.readouterr().out
    assert "2026-27 GW2-GW2: OPTIMAL" in output
    assert "Wrote" in output


def test_feasible_output_requires_an_explicit_shadow_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = _world(tmp_path)
    request = _request(world, tmp_path)
    original = horizon_service.plan_transfer_horizon
    cached: list[tuple[TransferPlanResult, TransferPlanningConfig]] = []

    def feasible_plan(
        *args: Any, **kwargs: Any
    ) -> tuple[TransferPlanResult, TransferPlanningConfig]:
        if not cached:
            cached.append(original(*args, **kwargs))
        plan, config = cached[0]
        return (
            replace(
                plan,
                solver_status=SolverStatus.FEASIBLE,
                diagnostics={**dict(plan.diagnostics), "relative_optimality_gap": 0.05},
            ),
            config,
        )

    monkeypatch.setattr(horizon_service, "plan_transfer_horizon", feasible_plan)

    with pytest.raises(DataError, match="allow_feasible_shadow=True"):
        plan_horizon(request)
    assert not request.artifact_root.exists()

    shadow = plan_horizon(replace(request, allow_feasible_shadow=True))
    assert shadow.publication_status == "shadow_only"
    assert shadow.document["decision_role"] == "research_shadow"
    assert shadow.document["solver_proof_status"] == "unproven"
    assert shadow.artifact_path.is_file()


def test_horizon_rejects_an_unpromoted_handoff_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = _world(tmp_path)
    request = _request(world, tmp_path)
    original = horizon_service.read_projection_handoff(request.in_season_projection)
    monkeypatch.setattr(
        horizon_service,
        "read_projection_handoff",
        lambda _path: replace(original, model_version="unpromoted-candidate-v1"),
    )

    with pytest.raises(DataError, match="not a promoted in-season control"):
        plan_horizon(request)
    assert not request.artifact_root.exists()


@pytest.mark.parametrize("status", [SolverStatus.INFEASIBLE, SolverStatus.UNKNOWN])
def test_horizon_does_not_write_an_artifact_without_a_complete_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: SolverStatus,
) -> None:
    world = _world(tmp_path)
    request = _request(world, tmp_path)
    original = horizon_service.plan_transfer_horizon
    cached: list[tuple[TransferPlanResult, TransferPlanningConfig]] = []

    def incomplete_plan(
        *args: Any, **kwargs: Any
    ) -> tuple[TransferPlanResult, TransferPlanningConfig]:
        if not cached:
            cached.append(original(*args, **kwargs))
        plan, config = cached[0]
        return (
            replace(
                plan,
                solver_status=status,
                weeks=(),
                total_projected_score=None,
                total_projected_bench_points=None,
                total_transfer_hit_points=None,
                objective_value=None,
            ),
            config,
        )

    monkeypatch.setattr(horizon_service, "plan_transfer_horizon", incomplete_plan)

    with pytest.raises(DataError, match=f"returned {status.name}"):
        plan_horizon(request)
    assert not request.artifact_root.exists()


def test_five_week_horizon_remains_a_shadow_artifact(tmp_path: Path) -> None:
    world = _world(tmp_path)
    result = plan_horizon(
        replace(
            _request(world, tmp_path),
            gameweeks=5,
            solver_deterministic_time_limit=100.0,
            allow_feasible_shadow=True,
        )
    )

    assert (result.first_gameweek, result.last_gameweek) == (2, 6)
    assert result.publication_status == "shadow_only"
    assert result.document["decision_role"] == "research_shadow"
    assert len(result.plan.weeks) == 5
    assert result.artifact_path.is_file()


@pytest.mark.parametrize("gameweeks", [True, 0, 2, 4, 5.0])
def test_request_rejects_an_unsupported_horizon(tmp_path: Path, gameweeks: object) -> None:
    with pytest.raises(DataError, match="1, 3, or 5"):
        HorizonPlanRequest(
            snapshot_root=tmp_path,
            ledger_root=tmp_path,
            artifact_root=tmp_path,
            in_season_projection=tmp_path / "handoff.json",
            gameweeks=gameweeks,  # type: ignore[arg-type]
        )


def test_writer_failure_before_publication_leaves_no_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "plan.json"

    def fail_durability(_file_descriptor: int) -> None:
        raise OSError("synthetic durability failure")

    monkeypatch.setattr(horizon_service.os, "fsync", fail_durability)
    with pytest.raises(OSError, match="synthetic durability failure"):
        horizon_service.write_horizon_plan(destination, {"contract_version": "test_v1"})

    assert not destination.exists()
    assert not list(tmp_path.glob(".plan.json.*.tmp"))


def test_concurrent_identical_application_writers_publish_once(tmp_path: Path) -> None:
    destination = tmp_path / "plan.json"
    document: dict[str, object] = {"contract_version": "test_v1", "value": 1}

    with ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = list(
            executor.map(
                lambda _index: horizon_service.write_horizon_plan(destination, document),
                range(8),
            )
        )

    assert outcomes.count(True) == 1
    assert outcomes.count(False) == 7
    assert json.loads(destination.read_text(encoding="utf-8")) == document
    assert not list(tmp_path.glob(".plan.json.*.tmp"))

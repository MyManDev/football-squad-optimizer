"""Transport-neutral application command for deterministic transfer horizons.

The live and planning packages calculate a multi-gameweek plan.  This module owns the
application boundary around that calculation: resolve immutable inputs, enforce the
publishability rule, and create one replay-safe operational artifact.  CLI, worker, and
API adapters can therefore call the same operation without reimplementing it.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Final

import pandas as pd

from squadopt.data.errors import DataError
from squadopt.data.snapshots import CapturedSnapshot, list_snapshot_ids, read_snapshot
from squadopt.live import (
    build_projection_horizon,
    held_squad_from_ledger,
    infer_season,
    plan_transfer_horizon,
    read_inputs,
    read_projection_handoff,
    read_season_rules,
)
from squadopt.optimization import OptimizationConfig, SolverStatus
from squadopt.planning import ProjectionHorizon, TransferPlanningConfig, TransferPlanResult

HORIZON_PLAN_ARTIFACT_CONTRACT_VERSION: Final = "live_transfer_horizon_v1"
SUPPORTED_HORIZON_LENGTHS: Final = frozenset({1, 3, 5})


@dataclass(frozen=True, slots=True)
class HorizonPlanRequest:
    """Inputs needed to plan from the squad held before an in-season deadline."""

    snapshot_root: Path
    ledger_root: Path
    artifact_root: Path
    in_season_projection: Path
    snapshot_id: str | None = None
    season: str | None = None
    from_gameweek: int | None = None
    gameweeks: int = 3
    solver_deterministic_time_limit: float | None = None
    solver_wall_ceiling_seconds: float = 300.0
    allow_feasible_shadow: bool = False
    output_path: Path | None = None

    def __post_init__(self) -> None:
        for name in ("snapshot_root", "ledger_root", "artifact_root", "in_season_projection"):
            object.__setattr__(self, name, Path(getattr(self, name)))
        if self.output_path is not None:
            object.__setattr__(self, "output_path", Path(self.output_path))
        if (
            isinstance(self.gameweeks, bool)
            or not isinstance(self.gameweeks, int)
            or self.gameweeks not in SUPPORTED_HORIZON_LENGTHS
        ):
            raise DataError("gameweeks must be one of 1, 3, or 5.")
        if self.from_gameweek is not None and (
            isinstance(self.from_gameweek, bool)
            or not isinstance(self.from_gameweek, int)
            or self.from_gameweek < 2
        ):
            raise DataError("from_gameweek must be an integer of 2 or greater.")
        for name in ("solver_deterministic_time_limit", "solver_wall_ceiling_seconds"):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int | float) or value <= 0
            ):
                raise DataError(f"{name} must be a positive number when supplied.")
        if not isinstance(self.allow_feasible_shadow, bool):
            raise DataError("allow_feasible_shadow must be a boolean.")


@dataclass(frozen=True, slots=True)
class HorizonPlanResult:
    """A structured multi-gameweek result and its immutable artifact location."""

    season: str
    first_gameweek: int
    last_gameweek: int
    snapshot_id: str
    solver_status: SolverStatus
    publication_status: str
    artifact_path: Path
    artifact_fingerprint: str
    created: bool
    plan: TransferPlanResult
    document: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact_path", Path(self.artifact_path))
        object.__setattr__(self, "document", MappingProxyType(dict(self.document)))


def _resolve_snapshot(root: Path, requested: str | None) -> tuple[str, CapturedSnapshot]:
    identifiers = list_snapshot_ids(root)
    if requested is not None:
        if requested not in identifiers:
            raise DataError(
                f"No snapshot {requested!r} under {root}. Held: "
                f"{identifiers[-3:] if identifiers else 'none'}."
            )
        snapshot_id = requested
    elif identifiers:
        snapshot_id = identifiers[-1]
    else:
        raise DataError(f"No snapshots under {root}.")
    return snapshot_id, read_snapshot(root, snapshot_id)


def _player_rows(frame: pd.DataFrame) -> list[dict[str, object]]:
    return [
        {
            "player_id": int(str(row.player_id)),
            "name": str(row.name),
            "team_id": str(row.team_id),
            "position": str(row.position),
            "price_tenths": int(str(row.price_tenths)),
            "expected_points": float(str(row.expected_points)),
        }
        for row in frame.itertuples(index=False)
    ]


def horizon_plan_document(
    horizon: ProjectionHorizon,
    plan: TransferPlanResult,
    transfer_config: TransferPlanningConfig,
) -> dict[str, object]:
    """Serialize a planner result as a deterministic operational artifact."""

    if not isinstance(horizon, ProjectionHorizon):
        raise TypeError("horizon must be a ProjectionHorizon.")
    if not isinstance(plan, TransferPlanResult):
        raise TypeError("plan must be a TransferPlanResult.")
    if not isinstance(transfer_config, TransferPlanningConfig):
        raise TypeError("transfer_config must be a TransferPlanningConfig.")
    diagnostics = {
        key: value for key, value in plan.diagnostics.items() if key != "solve_time_seconds"
    }
    document: dict[str, object] = {
        "artifact_type": "live_transfer_horizon",
        "contract_version": HORIZON_PLAN_ARTIFACT_CONTRACT_VERSION,
        "season": horizon.season,
        "source_snapshot_id": horizon.source_snapshot_id,
        "projection_horizon_contract_version": horizon.contract_version,
        "projection_horizon_fingerprint": horizon.horizon_fingerprint,
        "model_name": horizon.model_name,
        "model_version": horizon.model_version,
        "feature_contract_version": horizon.feature_contract_version,
        "post_processing_contract_version": horizon.post_processing_contract_version,
        "target_gameweeks": list(horizon.target_gameweeks),
        "transfer_planning_contract_version": plan.contract_version,
        "transfer_configuration_fingerprint": transfer_config.configuration_fingerprint,
        "transfer_policy": {
            "max_transfers_per_gameweek": transfer_config.max_transfers_per_gameweek,
            "transfer_hit_cost_points": transfer_config.transfer_hit_cost_points,
            "banked_transfer_value_points": transfer_config.banked_transfer_value_points,
        },
        "solver_status": plan.solver_status.name,
        "publication_status": (
            "proven" if plan.solver_status is SolverStatus.OPTIMAL else "shadow_unproven"
        ),
        "objective_value": plan.objective_value,
        "total_projected_score": plan.total_projected_score,
        "total_projected_bench_points": plan.total_projected_bench_points,
        "total_transfer_hit_points": plan.total_transfer_hit_points,
        "diagnostics": diagnostics,
        "weeks": [
            {
                "gameweek": week.gameweek,
                "squad": _player_rows(week.selected_squad),
                "starting_xi": _player_rows(week.starting_xi),
                "bench": _player_rows(week.bench),
                "captain_player_id": int(week.captain["player_id"]),
                "transfers_in": _player_rows(week.transfers_in),
                "transfers_out": _player_rows(week.transfers_out),
                "transfer_count": week.transfer_count,
                "paid_transfer_count": week.paid_transfer_count,
                "transfer_hit_points": week.transfer_hit_points,
                "bank_before_tenths": week.bank_before_tenths,
                "bank_after_tenths": week.bank_after_tenths,
                "free_transfers_before": week.free_transfers_before,
                "free_transfers_for_next_gameweek": week.free_transfers_for_next_gameweek,
                "projected_score": week.projected_score,
                "projected_bench_points": week.projected_bench_points,
            }
            for week in plan.weeks
        ],
        "stated_limits": [
            "Player projections and availability are frozen at the first decision snapshot.",
            "Only the captured fixture calendar varies across later gameweeks.",
            "Prices are held fixed; no price-transition model is applied.",
            "This artifact contains deterministic expected-point outputs only.",
        ],
    }
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    document["artifact_fingerprint"] = hashlib.sha256(encoded).hexdigest()
    return document


def write_horizon_plan(path: Path, document: Mapping[str, object]) -> bool:
    """Atomically create an immutable artifact, accepting an identical replay."""

    destination = Path(path)
    serialized = json.dumps(dict(document), indent=2, sort_keys=True) + "\n"
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary_path, destination)
        except FileExistsError:
            if destination.read_text(encoding="utf-8") != serialized:
                raise DataError(
                    f"Refusing to overwrite {destination}: an artifact with different content "
                    "already exists at this immutable path."
                ) from None
            return False
        return True
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def plan_horizon(request: HorizonPlanRequest) -> HorizonPlanResult:
    """Plan, validate, and immutably record one deterministic transfer horizon."""

    snapshot_id, snapshot = _resolve_snapshot(request.snapshot_root, request.snapshot_id)
    season = request.season or infer_season(snapshot)
    handoff = read_projection_handoff(request.in_season_projection)
    first = request.from_gameweek or handoff.gameweek
    targets = tuple(range(first, first + request.gameweeks))
    inputs = read_inputs(snapshot, season=season, gameweek=first)
    horizon = build_projection_horizon(
        snapshot,
        targets,
        season=season,
        in_season=handoff,
    )
    held = held_squad_from_ledger(
        request.ledger_root,
        season,
        before_gameweek=first,
        budget_tenths=OptimizationConfig().budget_tenths,
    )
    rules = read_season_rules(snapshot, season=season)
    deterministic_limit = request.solver_deterministic_time_limit or 20.0 * request.gameweeks
    optimization = OptimizationConfig(
        solver_time_limit_seconds=request.solver_wall_ceiling_seconds,
        solver_deterministic_time_limit=deterministic_limit,
    )
    plan, transfer_config = plan_transfer_horizon(
        inputs,
        horizon,
        held,
        rules,
        optimization=optimization,
    )
    if plan.solver_status not in {SolverStatus.OPTIMAL, SolverStatus.FEASIBLE}:
        raise DataError(
            f"The {request.gameweeks}-week planner returned {plan.solver_status.name}; "
            "there is no complete plan artifact to record."
        )
    if plan.solver_status is SolverStatus.FEASIBLE and not request.allow_feasible_shadow:
        used = plan.diagnostics.get("deterministic_time_used")
        gap = plan.diagnostics.get("relative_optimality_gap")
        raise DataError(
            f"The {request.gameweeks}-week plan is {plan.solver_status.name}, not proven "
            f"optimal (deterministic time {used!r}, relative gap {gap!r}). It may only "
            "be written explicitly with allow_feasible_shadow=True."
        )
    document = horizon_plan_document(horizon, plan, transfer_config)
    fingerprint = str(document["artifact_fingerprint"])
    destination = request.output_path or (
        request.artifact_root
        / season
        / f"gw{first:02d}"
        / f"h{request.gameweeks}"
        / f"transfer_horizon_{fingerprint[:16]}.json"
    )
    created = write_horizon_plan(destination, document)
    return HorizonPlanResult(
        season=season,
        first_gameweek=first,
        last_gameweek=targets[-1],
        snapshot_id=snapshot_id,
        solver_status=plan.solver_status,
        publication_status=str(document["publication_status"]),
        artifact_path=destination,
        artifact_fingerprint=fingerprint,
        created=created,
        plan=plan,
        document=document,
    )

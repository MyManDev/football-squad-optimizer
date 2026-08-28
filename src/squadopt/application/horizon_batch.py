"""Run the deterministic one-, three-, and five-week planning evidence together."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Final

from squadopt.application.horizon_plans import (
    SUPPORTED_HORIZON_LENGTHS,
    HorizonPlanRequest,
    HorizonPlanResult,
    plan_horizon,
    write_horizon_plan,
)
from squadopt.data.errors import DataError

HORIZON_BATCH_CONTRACT_VERSION: Final = "live_transfer_horizon_batch_v1"
DEFAULT_HORIZONS: Final = (1, 3, 5)
DEFAULT_SHADOW_HORIZONS: Final = frozenset({3, 5})

HorizonPlanner = Callable[[HorizonPlanRequest], HorizonPlanResult]


@dataclass(frozen=True, slots=True)
class HorizonBatchRequest:
    """Inputs and proof policy for one replay-safe planning batch."""

    snapshot_root: Path
    ledger_root: Path
    artifact_root: Path
    in_season_projection: Path
    snapshot_id: str | None = None
    season: str | None = None
    from_gameweek: int | None = None
    horizons: tuple[int, ...] = DEFAULT_HORIZONS
    shadow_horizons: frozenset[int] = DEFAULT_SHADOW_HORIZONS
    deterministic_time_per_gameweek: float = 20.0
    solver_wall_ceiling_seconds: float = 300.0

    def __post_init__(self) -> None:
        for name in ("snapshot_root", "ledger_root", "artifact_root", "in_season_projection"):
            object.__setattr__(self, name, Path(getattr(self, name)))
        if not isinstance(self.horizons, tuple) or not self.horizons:
            raise DataError("horizons must be a non-empty tuple.")
        if any(isinstance(value, bool) or not isinstance(value, int) for value in self.horizons):
            raise DataError("Every horizon must be an integer.")
        if tuple(sorted(set(self.horizons))) != self.horizons:
            raise DataError("horizons must be unique and increasing.")
        unsupported = set(self.horizons) - SUPPORTED_HORIZON_LENGTHS
        if unsupported:
            raise DataError(f"Unsupported horizons: {sorted(unsupported)!r}; use 1, 3, or 5.")
        if 1 not in self.horizons:
            raise DataError("The batch must include the one-week live control horizon.")
        if not isinstance(self.shadow_horizons, frozenset) or any(
            isinstance(value, bool) or not isinstance(value, int) for value in self.shadow_horizons
        ):
            raise DataError("shadow_horizons must be a frozenset of integers.")
        if not self.shadow_horizons.issubset(self.horizons):
            raise DataError("shadow_horizons must be a subset of horizons.")
        if 1 in self.shadow_horizons:
            raise DataError("The one-week live control cannot be a shadow horizon.")
        for name in ("deterministic_time_per_gameweek", "solver_wall_ceiling_seconds"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
                raise DataError(f"{name} must be a positive number.")


@dataclass(frozen=True, slots=True)
class HorizonBatchResult:
    """Every horizon result plus the immutable manifest joining their lineage."""

    season: str
    first_gameweek: int
    snapshot_id: str
    plans: tuple[HorizonPlanResult, ...]
    manifest_path: Path
    batch_fingerprint: str
    created: bool
    manifest: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "manifest_path", Path(self.manifest_path))
        object.__setattr__(self, "manifest", MappingProxyType(dict(self.manifest)))


def _relative_artifact(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as error:
        raise DataError(f"Horizon artifact {path} is outside artifact_root {root}.") from error


def _manifest(
    request: HorizonBatchRequest, plans: tuple[HorizonPlanResult, ...]
) -> dict[str, object]:
    first = plans[0]
    rows: list[dict[str, object]] = []
    for result in plans:
        diagnostics = result.plan.diagnostics
        gap = diagnostics.get("relative_optimality_gap")
        rows.append(
            {
                "horizon": result.last_gameweek - result.first_gameweek + 1,
                "decision_role": (
                    "live_control"
                    if result.last_gameweek == result.first_gameweek
                    else "research_shadow"
                ),
                "target_gameweeks": list(range(result.first_gameweek, result.last_gameweek + 1)),
                "solver_status": result.solver_status.name,
                "solver_proof_status": result.publication_status,
                "relative_optimality_gap": (float(str(gap)) if gap is not None else None),
                "artifact_fingerprint": result.artifact_fingerprint,
                "artifact_path": _relative_artifact(result.artifact_path, request.artifact_root),
            }
        )
    document: dict[str, object] = {
        "artifact_type": "live_transfer_horizon_batch",
        "contract_version": HORIZON_BATCH_CONTRACT_VERSION,
        "season": first.season,
        "source_snapshot_id": first.snapshot_id,
        "first_gameweek": first.first_gameweek,
        "decision_horizon": 1,
        "shadow_horizons": sorted(request.shadow_horizons),
        "public_advice_policy": "only_the_one_week_control_is_decision_eligible",
        "horizons": rows,
        "stated_limits": [
            "Longer horizons are research shadows and cannot replace the live control.",
            "Solver proof establishes optimization status, not forecast calibration.",
            "This batch contains deterministic expected-point outputs only.",
        ],
    }
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    document["batch_fingerprint"] = hashlib.sha256(encoded).hexdigest()
    return document


def plan_horizon_batch(
    request: HorizonBatchRequest,
    *,
    planner: HorizonPlanner = plan_horizon,
) -> HorizonBatchResult:
    """Run every requested horizon and join complete results in one manifest."""

    plans: list[HorizonPlanResult] = []
    for horizon in request.horizons:
        plans.append(
            planner(
                HorizonPlanRequest(
                    snapshot_root=request.snapshot_root,
                    ledger_root=request.ledger_root,
                    artifact_root=request.artifact_root,
                    in_season_projection=request.in_season_projection,
                    snapshot_id=request.snapshot_id,
                    season=request.season,
                    from_gameweek=request.from_gameweek,
                    gameweeks=horizon,
                    solver_deterministic_time_limit=(
                        request.deterministic_time_per_gameweek * horizon
                    ),
                    solver_wall_ceiling_seconds=request.solver_wall_ceiling_seconds,
                    allow_feasible_shadow=horizon in request.shadow_horizons,
                )
            )
        )
    completed = tuple(plans)
    first = completed[0]
    if any(
        result.season != first.season
        or result.snapshot_id != first.snapshot_id
        or result.first_gameweek != first.first_gameweek
        for result in completed[1:]
    ):
        raise DataError("Every horizon in a batch must share season, snapshot, and origin.")
    manifest = _manifest(request, completed)
    fingerprint = str(manifest["batch_fingerprint"])
    destination = (
        request.artifact_root
        / first.season
        / f"gw{first.first_gameweek:02d}"
        / "batches"
        / f"horizon_batch_{fingerprint[:16]}.json"
    )
    created = write_horizon_plan(destination, manifest)
    return HorizonBatchResult(
        season=first.season,
        first_gameweek=first.first_gameweek,
        snapshot_id=first.snapshot_id,
        plans=completed,
        manifest_path=destination,
        batch_fingerprint=fingerprint,
        created=created,
        manifest=manifest,
    )

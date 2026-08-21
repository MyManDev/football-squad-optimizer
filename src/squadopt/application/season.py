"""Public application service for one scheduled season tick.

Planning remains a pure live-domain operation.  This module supplies the application
boundary around it: read current state, execute due commands through the public
decision and settlement services, and accept the network capture as an injected
entry-point dependency.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, TypeAlias

from squadopt.application.commands import (
    DecideRequest,
    DecideResult,
    PanelBuilder,
    SettleRequest,
    SettleResult,
    decide,
    settle,
)
from squadopt.data.errors import DataError
from squadopt.data.snapshots import (
    CapturedSnapshot,
    SnapshotMetadata,
    list_snapshot_ids,
    read_snapshot,
)
from squadopt.data.sources.vaastav import build_panel
from squadopt.live import LedgerError, infer_season, load_ledger
from squadopt.live.tick import (
    HeldSnapshot,
    LedgerState,
    TickAction,
    TickConfig,
    TickPlan,
    plan_tick,
)

CaptureOperation: TypeAlias = Callable[[Path], SnapshotMetadata | None]
TickValue: TypeAlias = SnapshotMetadata | DecideResult | SettleResult


class TickObserver(Protocol):
    """Optional lifecycle observer implemented by CLI logging or later telemetry."""

    def planned(self, plan: TickPlan, *, replanned: bool) -> None: ...

    def action_started(self, action: TickAction) -> None: ...

    def action_completed(self, action: TickAction, value: TickValue) -> None: ...

    def action_failed(self, action: TickAction, error: Exception) -> None: ...


@dataclass(frozen=True, slots=True)
class TickRequest:
    """Filesystem roots, clock, and timing policy for one repeatable tick."""

    snapshot_root: Path
    ledger_root: Path
    archive_root: Path
    handoff_root: Path
    summary_root: Path
    now_utc: str
    season: str | None = None
    summary_output: Path | None = None
    config: TickConfig = field(default_factory=TickConfig)

    def __post_init__(self) -> None:
        for name in (
            "snapshot_root",
            "ledger_root",
            "archive_root",
            "handoff_root",
            "summary_root",
        ):
            object.__setattr__(self, name, Path(getattr(self, name)))
        if self.summary_output is not None:
            object.__setattr__(self, "summary_output", Path(self.summary_output))
        if not isinstance(self.now_utc, str) or not self.now_utc.strip():
            raise DataError("now_utc must be a non-empty UTC timestamp.")
        if not isinstance(self.config, TickConfig):
            raise DataError("config must be a TickConfig.")


@dataclass(frozen=True, slots=True)
class PerformedTickAction:
    """One state-changing action successfully completed during a tick."""

    action: TickAction
    value: TickValue


@dataclass(frozen=True, slots=True)
class TickResult:
    """The plans observed and every action completed by one tick."""

    request: TickRequest
    plans: tuple[TickPlan, ...]
    performed: tuple[PerformedTickAction, ...]
    dry_run: bool

    @property
    def final_plan(self) -> TickPlan:
        return self.plans[-1]

    @property
    def action_count(self) -> int:
        return len(self.performed)


def _read_state(
    request: TickRequest,
) -> tuple[list[HeldSnapshot], CapturedSnapshot | None, str | None, LedgerState]:
    identifiers = list_snapshot_ids(request.snapshot_root)
    held: list[HeldSnapshot] = []
    latest: CapturedSnapshot | None = None
    for identifier in identifiers:
        snapshot = read_snapshot(request.snapshot_root, identifier)
        held.append(HeldSnapshot(identifier, snapshot.metadata.captured_at_utc))
        latest = snapshot
    season = request.season or (infer_season(latest) if latest is not None else None)
    ledger = LedgerState()
    if season is not None:
        entries = load_ledger(request.ledger_root, season)
        ledger = LedgerState(
            decided=frozenset(entry.gameweek for entry in entries),
            settled=frozenset(entry.gameweek for entry in entries if entry.outcome is not None),
        )
    return held, latest, season, ledger


def plan_season_tick(request: TickRequest) -> TickPlan:
    """Read current application state and return the pure live-domain plan."""

    held, latest, season, ledger = _read_state(request)
    return plan_tick(
        now_utc=request.now_utc,
        held=held,
        latest=latest,
        ledger=ledger,
        handoff_root=request.handoff_root,
        config=request.config,
        season=season,
    )


def _execute_action(
    action: TickAction,
    request: TickRequest,
    *,
    season: str | None,
    capture: CaptureOperation | None,
    panel_builder: PanelBuilder,
) -> TickValue:
    if action.kind == "capture":
        if capture is None:
            raise DataError("This tick needs a capture operation, but none was supplied.")
        metadata = capture(request.snapshot_root)
        if metadata is None:
            raise DataError("The capture operation returned no snapshot.")
        return metadata
    if action.kind == "decide":
        return decide(
            DecideRequest(
                snapshot_root=request.snapshot_root,
                snapshot_id=action.snapshot_id,
                gameweek=action.gameweek,
                season=season,
                ledger_root=request.ledger_root,
                archive_root=request.archive_root,
                in_season_projection=(
                    Path(action.handoff_path) if action.handoff_path is not None else None
                ),
                mode="live",
            ),
            panel_builder=panel_builder,
        )
    if action.kind == "settle":
        if action.gameweek is None:
            raise LedgerError("A settle action must name its gameweek.")
        return settle(
            SettleRequest(
                snapshot_root=request.snapshot_root,
                snapshot_id=action.snapshot_id,
                gameweek=action.gameweek,
                season=season,
                ledger_root=request.ledger_root,
                summary_root=request.summary_root,
                summary_output=request.summary_output,
            )
        )
    raise DataError(f"Tick action {action.kind!r} does not change application state.")


def run_season_tick(
    request: TickRequest,
    *,
    capture: CaptureOperation | None = None,
    panel_builder: PanelBuilder = build_panel,
    dry_run: bool = False,
    observer: TickObserver | None = None,
) -> TickResult:
    """Execute everything due now, re-planning once after any capture.

    A caller may omit ``capture`` when the plan is known not to require network I/O or
    during a dry run.  Domain failures propagate unchanged so CLI, HTTP, and workers
    can map the same failure to their own transport without changing command behavior.
    """

    plan = plan_season_tick(request)
    plans = [plan]
    if observer is not None:
        observer.planned(plan, replanned=False)
    if dry_run:
        return TickResult(request=request, plans=tuple(plans), performed=(), dry_run=True)

    performed: list[PerformedTickAction] = []

    def perform(action: TickAction, season: str | None) -> None:
        if observer is not None:
            observer.action_started(action)
        try:
            value = _execute_action(
                action,
                request,
                season=season,
                capture=capture,
                panel_builder=panel_builder,
            )
        except Exception as error:
            if observer is not None:
                observer.action_failed(action, error)
            raise
        performed.append(PerformedTickAction(action, value))
        if observer is not None:
            observer.action_completed(action, value)

    if plan.wants_capture:
        for action in plan.actions:
            if action.kind == "capture":
                perform(action, plan.season)
        plan = plan_season_tick(request)
        plans.append(plan)
        if observer is not None:
            observer.planned(plan, replanned=True)

    for action in plan.actions:
        if action.kind in {"decide", "settle"}:
            perform(action, plan.season)

    return TickResult(
        request=request,
        plans=tuple(plans),
        performed=tuple(performed),
        dry_run=False,
    )

"""Installed static-site assembly from ledger state and an optional pinned capture."""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from squadopt.application.season import TickRequest, plan_season_tick
from squadopt.application.site import SiteBuildReport, build_site
from squadopt.data.errors import DataError
from squadopt.data.snapshots import list_snapshot_ids, read_snapshot
from squadopt.data.sources import FPL_LIVE_SOURCE
from squadopt.live import infer_season, load_ledger
from squadopt.live.tick import HeldSnapshot, LedgerState, TickConfig, plan_tick


@dataclass(frozen=True, slots=True)
class SitePublicationRequest:
    snapshot_root: Path
    ledger_root: Path
    archive_root: Path
    handoff_root: Path
    summary_root: Path
    log_root: Path
    out_dir: Path
    season: str | None = None
    snapshot_id: str | None = None
    now_utc: str | None = None
    include_status: bool = True
    include_league: bool = True
    horizon_manifest: Path | None = None


@dataclass(frozen=True, slots=True)
class SitePublicationResult:
    report: SiteBuildReport
    snapshot_id: str | None

    @property
    def output_paths(self) -> tuple[Path, ...]:
        return tuple(self.report.out_dir / "data" / name for name in self.report.files)


class SiteSeasonUnavailableError(DataError):
    """The read-only publication could not infer a season."""


def publish_site(request: SitePublicationRequest) -> SitePublicationResult:
    """Read a view of the scheduler and ledger, without executing a tick action."""

    now_utc = request.now_utc or datetime.now(UTC).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )
    plan = None
    season = request.season
    snapshot = None
    if request.snapshot_id is not None:
        snapshot = read_snapshot(request.snapshot_root, request.snapshot_id)
        if snapshot.metadata.source != FPL_LIVE_SOURCE:
            raise DataError(
                f"Site capture {request.snapshot_id!r} is not an {FPL_LIVE_SOURCE} capture."
            )
    if request.include_status:
        tick = TickRequest(
            snapshot_root=request.snapshot_root,
            ledger_root=request.ledger_root,
            archive_root=request.archive_root,
            handoff_root=request.handoff_root,
            summary_root=request.summary_root,
            now_utc=now_utc,
            season=request.season,
            config=TickConfig(),
        )
        if snapshot is None:
            plan = plan_season_tick(tick)
        else:
            pinned_season = season or infer_season(snapshot)
            entries = load_ledger(request.ledger_root, pinned_season)
            state = LedgerState(
                decided=frozenset(entry.gameweek for entry in entries),
                settled=frozenset(entry.gameweek for entry in entries if entry.outcome is not None),
            )
            plan = plan_tick(
                now_utc=now_utc,
                held=[
                    HeldSnapshot(snapshot.metadata.snapshot_id, snapshot.metadata.captured_at_utc)
                ],
                latest=snapshot,
                ledger=state,
                handoff_root=request.handoff_root,
                config=tick.config,
                season=pinned_season,
            )
        season = season or plan.season
    if season is None:
        raise SiteSeasonUnavailableError("Season could not be inferred; pass --season.")
    if request.include_league and snapshot is None:
        identifiers = list_snapshot_ids(request.snapshot_root, source=FPL_LIVE_SOURCE)
        if identifiers:
            snapshot = read_snapshot(request.snapshot_root, identifiers[-1])
    report = build_site(
        ledger_root=request.ledger_root,
        season=str(season),
        out_dir=request.out_dir,
        plan=plan,
        runlog_root=request.log_root,
        snapshot=snapshot if request.include_league else None,
        horizon_manifest=request.horizon_manifest,
        now=datetime.fromisoformat(now_utc.replace("Z", "+00:00")),
    )
    return SitePublicationResult(
        report, snapshot.metadata.snapshot_id if snapshot is not None else None
    )

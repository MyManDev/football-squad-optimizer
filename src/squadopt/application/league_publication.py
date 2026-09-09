"""Installed assembly of a member publication from an explicit capture.

The service reads already captured inputs and writes the existing league/advice contracts.
Scheduling, process pools, argument parsing and console output are supplied by callers.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from squadopt.application.advice import member_horizon_builder
from squadopt.application.advice_record import record_directory
from squadopt.application.capture_entries import CapturePicksProvider
from squadopt.application.entries import EntryRegistration, EntryRegistry
from squadopt.application.league_views import (
    LeagueViewsReport,
    MemberMapper,
    MemberStanding,
    build_league_views,
)
from squadopt.application.mode_selection import build_mode_paths
from squadopt.data.errors import DataError
from squadopt.data.snapshots import CapturedSnapshot, list_snapshot_ids, read_snapshot
from squadopt.data.sources import FPL_LIVE_SOURCE
from squadopt.data.sources.fpl_live import (
    EntryGameweekPoints,
    fpl_entry_history_points,
    fpl_league_standings,
    scored_gameweeks,
)
from squadopt.data.sources.vaastav import build_panel
from squadopt.live import (
    RecommendationInputs,
    load_residual_history,
    project,
    read_inputs,
    read_projection_handoff,
    read_season_rules,
)
from squadopt.live.recommendation import infer_season


@dataclass(frozen=True, slots=True)
class LeaguePublicationRequest:
    snapshot_root: Path
    snapshot_id: str
    archive_root: Path
    registry_path: Path
    out_dir: Path
    league_id: int
    season: str | None = None
    gameweek: int | None = None
    handoff_path: Path | None = None
    mode_residuals: Path | None = None
    record_root: Path | None = None
    rival_menu: bool = True
    now: datetime | None = None


@dataclass(frozen=True, slots=True)
class PreparedLeaguePublication:
    request: LeaguePublicationRequest
    snapshot: CapturedSnapshot
    inputs: RecommendationInputs
    registrations: tuple[EntryRegistration, ...]
    season: str
    standings: Mapping[int, MemberStanding]
    scored_gameweek: int | None
    scored_members: int


@dataclass(frozen=True, slots=True)
class ModePathsSummary:
    scenario_count: int
    gameweek: int
    source_id: str


@dataclass(frozen=True, slots=True)
class LeaguePublicationResult:
    snapshot_id: str
    season: str
    gameweek: int
    report: LeagueViewsReport
    output_paths: tuple[Path, ...]


def member_points(
    payloads: Mapping[str, bytes], entry_ids: Sequence[int], *, gameweek: int
) -> dict[int, EntryGameweekPoints]:
    """Each member's score for one gameweek, from that member's own history.

    A member whose history the capture does not hold, or who has no row for this week, is
    **omitted** rather than recorded as zero: the caller publishes null for them, which
    says the capture does not prove their score. Omission is the honest answer and a zero
    would be a claim.
    """

    scores: dict[int, EntryGameweekPoints] = {}
    for entry_id in entry_ids:
        payload = payloads.get(f"entry-{entry_id}-history.json")
        if payload is None:
            continue
        for week in fpl_entry_history_points(payload, entry_id=entry_id):
            if week.gameweek == gameweek:
                scores[entry_id] = week
                break
    return scores


def last_scored_gameweek(bootstrap: bytes, *, before: int) -> int | None:
    """The most recent week whose points are final, earlier than the week being built.

    ``None`` while no week has been both finished and checked — before the opening
    deadline, and during the hours after the last whistle when bonus has not landed.
    """

    scored = [week for week in scored_gameweeks(bootstrap) if week < before]
    return max(scored) if scored else None


def resolve_live_snapshot_id(root: Path, requested: str | None) -> str:
    """The capture to read: the one named, or the most recent *live* one held.

    Only a live capture can serve the league tree; Top-100 and elite-picks captures share
    the snapshot root and sort after it by name, so "the latest snapshot" must not be
    "the last directory".
    """

    if requested:
        if requested not in list_snapshot_ids(root):
            raise DataError(f"No snapshot {requested!r} under {root}.")
        return requested
    live = list_snapshot_ids(root, source=FPL_LIVE_SOURCE)
    if not live:
        raise DataError(f"No {FPL_LIVE_SOURCE}-* snapshots under {root}; capture one first.")
    return live[-1]


def prepare_league_publication(request: LeaguePublicationRequest) -> PreparedLeaguePublication:
    """Read and validate the capture/registry without solving or writing a publication."""

    snapshot = read_snapshot(request.snapshot_root, request.snapshot_id)
    season = request.season or infer_season(snapshot)
    inputs = read_inputs(snapshot, season=season, gameweek=request.gameweek)
    registry = EntryRegistry.load(Path(request.registry_path))
    if not registry.entries:
        raise DataError(
            f"No registered entries in {request.registry_path}; seed it first with "
            "`python -m scripts.seed_entry_registry --league <id>`."
        )

    standings_name = f"league-{request.league_id}-standings.json"
    payloads = getattr(snapshot, "payloads", {})
    standings: dict[int, MemberStanding] = {}
    registered = [int(entry.entry_id) for entry in registry.entries]
    scored = last_scored_gameweek(
        payloads["bootstrap-static.json"], before=int(inputs.deadline.gameweek)
    )
    scores = member_points(payloads, registered, gameweek=scored) if scored is not None else {}
    if standings_name in payloads:
        rows = fpl_league_standings(payloads[standings_name], league_id=request.league_id)
        standings = {
            row.entry_id: MemberStanding(
                entry_id=row.entry_id,
                team_name=row.entry_name,
                manager_name=row.player_name,
                rank=row.rank,
                gameweek_points=(scores[row.entry_id].points if row.entry_id in scores else None),
                total_points=(
                    scores[row.entry_id].total_points if row.entry_id in scores else None
                ),
                transfer_cost=(
                    scores[row.entry_id].transfer_cost if row.entry_id in scores else None
                ),
            )
            for row in rows
        }
    return PreparedLeaguePublication(
        request=request,
        snapshot=snapshot,
        inputs=inputs,
        registrations=registry.entries,
        season=season,
        standings=standings,
        scored_gameweek=scored,
        scored_members=len(scores),
    )


def publish_league(
    request: LeaguePublicationRequest,
    *,
    mapper: MemberMapper = map,
    on_prepared: Callable[[PreparedLeaguePublication], None] | None = None,
    on_mode_paths: Callable[[ModePathsSummary], None] | None = None,
) -> LeaguePublicationResult:
    """Publish the existing contracts; callbacks observe progress without owning the work."""

    prepared = prepare_league_publication(request)
    if on_prepared is not None:
        on_prepared(prepared)
    return publish_prepared_league(prepared, mapper=mapper, on_mode_paths=on_mode_paths)


def publish_prepared_league(
    prepared: PreparedLeaguePublication,
    *,
    mapper: MemberMapper = map,
    on_mode_paths: Callable[[ModePathsSummary], None] | None = None,
) -> LeaguePublicationResult:
    """Complete a prepared publication without rereading a possibly changing selector."""

    request = prepared.request
    snapshot, inputs, season = prepared.snapshot, prepared.inputs, prepared.season
    panel = build_panel(request.archive_root)
    in_season = read_projection_handoff(request.handoff_path) if request.handoff_path else None
    projection = project(inputs, panel, in_season=in_season)
    mode_paths = None
    if request.mode_residuals:
        history = load_residual_history(request.mode_residuals)
        mode_paths = build_mode_paths(
            projection,
            history,
            season=season,
            gameweek=int(inputs.deadline.gameweek),
        )
        if on_mode_paths is not None:
            on_mode_paths(
                ModePathsSummary(
                    mode_paths.config.scenario_count,
                    int(inputs.deadline.gameweek),
                    history.source_id,
                )
            )
    out_dir = request.out_dir / "data" / "league"
    report = build_league_views(
        CapturePicksProvider(snapshot, request.snapshot_id),
        prepared.registrations,
        inputs,
        projection,
        read_season_rules(snapshot, season=season),
        league_id=request.league_id,
        league_name=f"League {request.league_id}",
        out_dir=out_dir,
        standings=prepared.standings,
        scored_gameweek=prepared.scored_gameweek,
        mode_paths=mode_paths,
        rival_menu=request.rival_menu,
        mapper=mapper,
        horizon_builder=member_horizon_builder(
            snapshot,
            season=season,
            panel=panel,
            in_season=in_season,
        ),
        advice_record_root=request.record_root,
        now=request.now,
    )
    outputs = [out_dir / name for name in report.files]
    if request.record_root is not None:
        for member in report.members:
            if member.rendered:
                directory = record_directory(
                    request.record_root,
                    season,
                    report.gameweek,
                    member.entry_id,
                    request.snapshot_id,
                )
                outputs.extend(path for path in directory.iterdir() if path.is_file())
    return LeaguePublicationResult(
        snapshot_id=request.snapshot_id,
        season=season,
        gameweek=report.gameweek,
        report=report,
        output_paths=tuple(sorted(outputs)),
    )

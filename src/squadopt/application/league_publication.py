"""Installed assembly of a member publication from an explicit capture.

The service reads already captured inputs and writes the existing league/advice contracts.
Scheduling, process pools, argument parsing and console output are supplied by callers.
"""

import shutil
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from squadopt.application.advice import member_horizon_builder
from squadopt.application.advice_record import record_directory
from squadopt.application.capture_entries import CapturePicksProvider
from squadopt.application.chip_forecast_publication import forecast_source
from squadopt.application.entries import EntryRegistration, EntryRegistry
from squadopt.application.league_views import (
    LeagueViewsReport,
    MemberMapper,
    MemberStanding,
    build_league_views,
)
from squadopt.application.manager_words import ManagerWords, load_manager_words
from squadopt.application.mode_selection import build_mode_paths
from squadopt.application.publication_history import explicit_archive_seasons
from squadopt.application.top100_weight import (
    Top100Counts,
    Top100InputsRefused,
    load_top100_counts,
)
from squadopt.application.weekly_suggestion_eval import (
    SUPPORTED_LEAGUE_ID,
    publish_suggestion_histories,
    published_advice_captures,
    published_page_captures,
)
from squadopt.contracts.league_tree import (
    LEGACY_TREE,
    LeagueDirectoryError,
    PublishedLeague,
    league_tree,
    league_tree_dir,
    legacy_tree_league_id,
    read_league_directory,
    write_league_directory,
)
from squadopt.data.atomic import replace_retrying
from squadopt.data.errors import DataError
from squadopt.data.snapshots import CapturedSnapshot, list_snapshot_ids, read_snapshot
from squadopt.data.sources import FPL_LIVE_SOURCE
from squadopt.data.sources.fpl_live import (
    EntryGameweekPoints,
    fpl_entry_history_points,
    fpl_league_name,
    fpl_league_standings,
    scored_gameweeks,
)
from squadopt.data.sources.vaastav import build_panel
from squadopt.live import (
    Projection,
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
    history_record_root: Path | None = None
    #: The week's rotation evidence table (its manifest beside it) and the club-news
    #: source it was coded from: the fixture file, or a capture directory. Both or
    #: neither; one without the other is refused, because words without their evidence
    #: are a paraphrase and evidence without its words is a claim nobody can read.
    rotation_evidence: Path | None = None
    club_news_source: Path | None = None
    #: The week's Top 100 evidence export (``player_evidence_v1`` csv, its manifest
    #: beside it). With it, every member gets the Top 100 influence menu; a table the
    #: handoff's own gate refuses turns the menu off with the reason, never the publish.
    top100_evidence: Path | None = None
    #: Explicit prospective inputs; current-season rows come from the named capture.
    #: None preserves the existing archive policy.
    training_seasons: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        if self.training_seasons is not None:
            explicit_archive_seasons(self.training_seasons)


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
    #: The league's own name from the capture's standings; ``None`` when it states none.
    league_name: str | None = None


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
    #: Why the Top 100 menu is off this run, for the operator; empty when it is on or
    #: was not asked for.
    top100_note: str = ""
    #: What became of a tree from before the league directory: "adopted" (moved to the
    #: league's path, its histories kept) or "removed" (a leftover beside a directory);
    #: empty when there was none.
    legacy_tree: str = ""
    #: This league's line of the site's directory, for a run that renders several leagues
    #: and lists each one beside the next.
    published: PublishedLeague | None = None


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
    if request.training_seasons is not None:
        explicit_archive_seasons(request.training_seasons, current_season=season)
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
    league_name: str | None = None
    registered = [int(entry.entry_id) for entry in registry.entries]
    scored = last_scored_gameweek(
        payloads["bootstrap-static.json"], before=int(inputs.deadline.gameweek)
    )
    scores = member_points(payloads, registered, gameweek=scored) if scored is not None else {}
    if standings_name in payloads:
        rows = fpl_league_standings(payloads[standings_name], league_id=request.league_id)
        league_name = fpl_league_name(payloads[standings_name], league_id=request.league_id)
        standings = {
            row.entry_id: MemberStanding(
                entry_id=row.entry_id,
                team_name=row.entry_name,
                manager_name=row.player_name,
                rank=row.rank,
                last_rank=row.last_rank,
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
        league_name=league_name,
    )


def publish_league(
    request: LeaguePublicationRequest,
    *,
    mapper: MemberMapper = map,
    on_prepared: Callable[[PreparedLeaguePublication], None] | None = None,
    on_mode_paths: Callable[[ModePathsSummary], None] | None = None,
    beside: Sequence[PublishedLeague] = (),
) -> LeaguePublicationResult:
    """Publish the existing contracts; callbacks observe progress without owning the work."""

    prepared = prepare_league_publication(request)
    if on_prepared is not None:
        on_prepared(prepared)
    return publish_prepared_league(
        prepared, mapper=mapper, on_mode_paths=on_mode_paths, beside=beside
    )


def load_publication_manager_words(request: LeaguePublicationRequest) -> ManagerWords | None:
    """The manager's word for this publication, or ``None`` when it names no evidence."""

    if request.rotation_evidence is None and request.club_news_source is None:
        return None
    if request.rotation_evidence is None or request.club_news_source is None:
        raise DataError(
            "The manager's word needs both the rotation evidence table and the club-news "
            "source it was coded from; one without the other is refused."
        )
    return load_manager_words(
        request.rotation_evidence,
        club_news_source=request.club_news_source,
        snapshot_root=request.snapshot_root,
    )


def load_publication_top100(
    request: LeaguePublicationRequest,
    inputs: RecommendationInputs,
    projection: Projection,
) -> tuple[Top100Counts | None, str | None, str]:
    """The week's Top 100 counts, or ``None`` with the index reason and the operator's note.

    ``(None, None, "")`` when the request names no evidence: the index then says the run
    read none. A refusal is a reason, not an error: the menu is an addition to the week,
    and the plans every member already gets do not depend on it.
    """

    if request.top100_evidence is None:
        return None, None, ""
    try:
        counts = load_top100_counts(request.top100_evidence, inputs=inputs, projection=projection)
    except Top100InputsRefused as refusal:
        return None, refusal.reason, f"Top 100 menu off ({refusal.reason}): {refusal}"
    return counts, None, ""


def adopt_legacy_tree(site_data_root: Path, league_id: int) -> tuple[str, Path] | None:
    """Make the legacy tree the league's own before a publication into the new layout.

    A site from before the directory carries the league under ``data/league/``; the
    documents there (the member histories above all, which carry every earlier week) are
    the league's, so the tree is moved to ``data/leagues/<league_id>/`` rather than left
    beside it or rebuilt from nothing: ``("adopted", new path)``. A legacy tree beside a
    directory is a leftover nothing lists, and is removed: ``("removed", its path)``.
    None where there is no legacy tree. A legacy tree naming another league on a site
    without a directory is left alone and refused: this publication cannot say whose it is.
    """

    root = Path(site_data_root)
    legacy = root / LEGACY_TREE
    if not legacy.is_dir():
        return None
    if read_league_directory(root):
        shutil.rmtree(legacy)
        return ("removed", legacy)
    named = legacy_tree_league_id(root)
    if named != league_id:
        raise LeagueDirectoryError(
            f"{legacy} names league {named}, not league {league_id}; it cannot be adopted."
        )
    target = league_tree_dir(root, league_id)
    if target.exists():
        raise LeagueDirectoryError(f"{target} exists beside the legacy tree {legacy}.")
    target.parent.mkdir(parents=True, exist_ok=True)
    # The one rename helper: it waits out the handle Windows may still hold on the tree.
    replace_retrying(legacy, target)
    return ("adopted", target)


def publish_prepared_league(
    prepared: PreparedLeaguePublication,
    *,
    mapper: MemberMapper = map,
    on_mode_paths: Callable[[ModePathsSummary], None] | None = None,
    beside: Sequence[PublishedLeague] = (),
) -> LeaguePublicationResult:
    """Complete a prepared publication without rereading a possibly changing selector.

    ``beside`` lists the other leagues the same run has rendered, so the site's directory
    is written with every league of the run: this one and those.
    """

    request = prepared.request
    snapshot, inputs, season = prepared.snapshot, prepared.inputs, prepared.season
    panel = (
        build_panel(
            request.archive_root,
            seasons=explicit_archive_seasons(request.training_seasons, current_season=season),
        )
        if request.training_seasons is not None
        else build_panel(request.archive_root)
    )
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
    site_data = request.out_dir / "data"
    # A tree from before the directory is this league's: adopted before anything reads
    # or writes the league's path, so its histories carry over.
    legacy = adopt_legacy_tree(site_data, request.league_id)
    out_dir = league_tree_dir(site_data, request.league_id)
    manager_words = load_publication_manager_words(request)
    if manager_words is not None and (manager_words.season, manager_words.gameweek) != (
        season,
        int(inputs.deadline.gameweek),
    ):
        raise DataError(
            f"The rotation evidence is for {manager_words.season} gameweek "
            f"{manager_words.gameweek}; this publication is {season} gameweek "
            f"{int(inputs.deadline.gameweek)}. Refused before any member is solved."
        )
    top100_counts, top100_reason, top100_note = load_publication_top100(request, inputs, projection)
    history_root = request.history_record_root or request.record_root
    if request.league_id != SUPPORTED_LEAGUE_ID:
        history_root = None
    # Read before the build below rewrites the tree: the tree this publication replaces is
    # the only place that says which capture each earlier week showed each member.
    shown = published_advice_captures(out_dir) if history_root is not None else {}
    report = build_league_views(
        CapturePicksProvider(snapshot, request.snapshot_id),
        prepared.registrations,
        inputs,
        projection,
        read_season_rules(snapshot, season=season),
        league_id=request.league_id,
        # The members know their league by its name. The number stands in only when the
        # capture states no name.
        league_name=prepared.league_name or f"League {request.league_id}",
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
        manager_words=manager_words,
        top100_counts=top100_counts,
        top100_unavailable_reason=top100_reason,
        chip_forecast_source=forecast_source(snapshot),
    )
    outputs = [out_dir / name for name in report.files]
    if history_root is not None:
        # This publication's own member pages name this week's capture.
        shown.update(published_page_captures(out_dir))
        outputs.extend(
            publish_suggestion_histories(
                record_root=history_root,
                snapshot_root=request.snapshot_root,
                as_of_snapshot=snapshot,
                season=season,
                league_id=request.league_id,
                entry_ids=[entry.entry_id for entry in prepared.registrations],
                out_dir=out_dir,
                published=shown,
            )
        )
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
    # The site's directory is what this run rendered: this league, beside the others the
    # run listed; a league the run did not render is not listed.
    published = PublishedLeague(
        league_id=report.league_id,
        league_name=report.league_name,
        season=report.season,
        gameweek=report.gameweek,
        path=league_tree(report.league_id).as_posix(),
    )
    directory = write_league_directory(
        site_data,
        [*(line for line in beside if line.league_id != published.league_id), published],
        generated_at_utc=report.generated_at_utc,
    )
    outputs.append(directory)
    return LeaguePublicationResult(
        snapshot_id=request.snapshot_id,
        season=season,
        gameweek=report.gameweek,
        report=report,
        output_paths=tuple(sorted(outputs)),
        top100_note=top100_note,
        legacy_tree=legacy[0] if legacy is not None else "",
        published=published,
    )

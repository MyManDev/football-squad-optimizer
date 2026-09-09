"""Write the site's league tree from a capture that read the registered entries.

    python -m scripts.build_league_site --league 352490 --out web/public
    python -m scripts.build_league_site --league 352490 --snapshot-id <id> --dry-run

The capture must have been taken with ``--entries`` so it holds each registered member's
three public documents plus the league standings page; ``scripts.seed_entry_registry``
writes the registry that names them. This shell reads those payloads, hands them to
``build_league_views`` through the ``EntryPicksProvider`` seam, and writes
``<out>/data/league/**``.

What it does not do is decide anything of ours: our season ledger is neither read nor
written here. A member's advice is computed from that member's own squad and the shared
projection, and the invariance test in ``tests/unit/test_league_views.py`` pins that as
fact rather than as intention.

It does record what it published. The site's advice paths carry no gameweek and are
overwritten every week, so ``build_league_views`` also writes an immutable advice record
under ``--advice-record-root``, one per member, gameweek and capture; without it, a week
that has been published can never afterwards be reviewed. A week is published more than
once — mid-week, then again with fresh availability before the deadline — and each of those
captures records its own, so the advice that stood at the deadline is on disk too.

Nothing personal is committed. The registry, the captures and the advice records stay
local (``.gitignore`` excludes ``data/entries/``, ``data/snapshots/`` and
``data/advice_records/``); what this writes under ``web/public`` is the public
post-deadline picture the league's own standings page already shows.
"""

import argparse
import functools
import multiprocessing
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import Executor, ProcessPoolExecutor
from contextlib import ExitStack
from pathlib import Path
from typing import Any

from squadopt.application.advice import member_horizon_builder
from squadopt.application.advice_record import AdviceRecordConflictError
from squadopt.application.entries import EntryRegistry
from squadopt.application.league_views import (
    MemberRender,
    MemberRenderTask,
    MemberStanding,
    build_league_views,
    render_member,
)
from squadopt.application.mode_selection import build_mode_paths
from squadopt.data.errors import DataError
from squadopt.data.snapshots import list_snapshot_ids, read_snapshot
from squadopt.data.sources import FPL_LIVE_SOURCE
from squadopt.data.sources.fpl_live import (
    EntryGameweekPoints,
    fpl_entry_history_points,
    fpl_league_standings,
    scored_gameweeks,
)
from squadopt.data.sources.vaastav import build_panel
from squadopt.live import (
    load_residual_history,
    project,
    read_inputs,
    read_projection_handoff,
    read_season_rules,
)
from squadopt.live.recommendation import infer_season
from squadopt.platform.capture_context import CapturePicksProvider


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


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_ROOT = REPOSITORY_ROOT / "data" / "snapshots"
ARCHIVE_ROOT = REPOSITORY_ROOT / "data" / "raw" / "vaastav-fpl"
REGISTRY_PATH = REPOSITORY_ROOT / "data" / "entries" / "registry.json"
#: Where the immutable per-member, per-gameweek advice record lands. Local like the
#: captures and the registry: it names identifiable people's squads, so ``.gitignore``
#: keeps it out of the repository for the same reason ``data/entries/`` is out.
ADVICE_RECORD_ROOT = REPOSITORY_ROOT / "data" / "advice_records"


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


# --- the process pool ----------------------------------------------------------------
#
# The capture context (snapshot payloads, inputs, projection, season rules) holds
# read-only mapping proxies and is not picklable, and it is large; so a worker does not
# receive it — it rebuilds the same context from the same paths once, at start, and the
# tasks that cross the process boundary are the primitive ``MemberRenderTask`` records.
# The projection is a deterministic function of the capture and the handoff, so a
# worker's context is the batch's context, and the bytes are the same (the in-process
# mapper test pins the scheduler-only property; the real run is checked by hand).

_WORKER_CONTEXT: dict[str, Any] = {}


def _worker_init(
    snapshot_root: str,
    snapshot_id: str,
    season: str,
    handoff: str | None,
    archive_root: str,
) -> None:
    snapshot = read_snapshot(Path(snapshot_root), snapshot_id)
    inputs = read_inputs(snapshot, season=season, gameweek=None)
    panel = build_panel(Path(archive_root))
    in_season = read_projection_handoff(Path(handoff)) if handoff else None
    _WORKER_CONTEXT.update(
        provider=CapturePicksProvider(snapshot, snapshot_id),
        inputs=inputs,
        projection=project(inputs, panel, in_season=in_season),
        rules=read_season_rules(snapshot, season=season),
        # The multi-week horizon is built once per window in each worker and shared by
        # every member the worker renders; it is the same bytes in every process.
        horizon_builder=member_horizon_builder(
            snapshot, season=season, panel=panel, in_season=in_season
        ),
    )


def _render_in_worker(task: MemberRenderTask) -> MemberRender:
    return render_member(task, **_WORKER_CONTEXT)


def pool_mapper(
    executor: Executor,
) -> Callable[
    [Callable[[MemberRenderTask], MemberRender], Iterable[MemberRenderTask]],
    Iterable[MemberRender],
]:
    """A ``build_league_views`` mapper over a pool whose workers hold their own context.

    The function the batch hands over is ``render_member`` bound to the batch's own
    context; the pool cannot carry that context, so it runs the same ``render_member``
    against the worker's — and refuses anything else, so a different function can never
    be silently replaced by this one.
    """

    def mapper(
        function: Callable[[MemberRenderTask], MemberRender],
        tasks: Iterable[MemberRenderTask],
    ) -> Iterable[MemberRender]:
        if not (isinstance(function, functools.partial) and function.func is render_member):
            raise ValueError("The pool mapper runs render_member only.")
        return executor.map(_render_in_worker, list(tasks))

    return mapper


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league", type=int, required=True)
    parser.add_argument("--snapshot-id", help="default: the most recent live capture")
    parser.add_argument("--snapshot-root", type=Path, default=SNAPSHOT_ROOT)
    parser.add_argument("--out", default="web/public")
    parser.add_argument("--season")
    parser.add_argument("--archive-root", default=str(ARCHIVE_ROOT))
    parser.add_argument("--registry", default=str(REGISTRY_PATH))
    parser.add_argument(
        "--in-season-projection",
        type=Path,
        help="projection handoff for this capture and gameweek; required from GW2 on, "
        "the same file the decision reads (projection_handoff_v1)",
    )
    parser.add_argument(
        "--mode-residuals",
        type=Path,
        help="residual export (csv/parquet beside its manifest) to build one-week scenario "
        "paths from; turns on the competitive play modes. When given, a history that "
        "cannot honestly support paths fails the run rather than silently downgrading.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="member tasks solved in parallel processes (each solver stays single-threaded); "
        "the bytes do not depend on this",
    )
    parser.add_argument(
        "--no-rival-menu",
        action="store_true",
        help="write the saf-puan baseline only; skip the rival strategies against every "
        "other member",
    )
    parser.add_argument(
        "--advice-record-root",
        type=Path,
        default=ADVICE_RECORD_ROOT,
        help="where the immutable per-member, per-gameweek, per-capture advice record is "
        "written; the published tree has no gameweek in its paths and is overwritten every "
        "week, so without this nothing survives to say what a member was told for a given "
        "week",
    )
    parser.add_argument(
        "--no-advice-record",
        action="store_true",
        help="publish without recording what was published; a week built this way can "
        "never be reviewed",
    )
    parser.add_argument("--dry-run", action="store_true", help="report, write nothing")
    arguments = parser.parse_args()
    if arguments.workers < 1:
        parser.error("--workers must be at least 1")

    try:
        snapshot_root = Path(arguments.snapshot_root)
        snapshot_id = resolve_live_snapshot_id(snapshot_root, arguments.snapshot_id)
        snapshot = read_snapshot(snapshot_root, snapshot_id)
        season = arguments.season or infer_season(snapshot)
        inputs = read_inputs(snapshot, season=season, gameweek=None)
        registry = EntryRegistry.load(Path(arguments.registry))
        if not registry.entries:
            raise DataError(
                f"No registered entries in {arguments.registry}; seed it first with "
                "`python -m scripts.seed_entry_registry --league <id>`."
            )

        standings_name = f"league-{arguments.league}-standings.json"
        payloads = getattr(snapshot, "payloads", {})
        standings: dict[int, MemberStanding] = {}
        league_name = f"League {arguments.league}"
        registered = [int(entry.entry_id) for entry in registry.entries]
        scored = last_scored_gameweek(
            payloads["bootstrap-static.json"], before=int(inputs.deadline.gameweek)
        )
        scores = member_points(payloads, registered, gameweek=scored) if scored is not None else {}
        if standings_name in payloads:
            rows = fpl_league_standings(payloads[standings_name], league_id=arguments.league)
            standings = {
                row.entry_id: MemberStanding(
                    entry_id=row.entry_id,
                    team_name=row.entry_name,
                    manager_name=row.player_name,
                    rank=row.rank,
                    gameweek_points=(
                        scores[row.entry_id].points if row.entry_id in scores else None
                    ),
                    total_points=(
                        scores[row.entry_id].total_points if row.entry_id in scores else None
                    ),
                    transfer_cost=(
                        scores[row.entry_id].transfer_cost if row.entry_id in scores else None
                    ),
                )
                for row in rows
            }
        scored_note = (
            f"points for {len(scores)} of {len(registered)} from gameweek {scored}"
            if scored is not None
            else "no scored gameweek yet, so no points are published"
        )
        print(
            f"capture {snapshot_id}: {len(registry.entries)} registered, "
            f"{len(standings)} in the standings, targeting {season} "
            f"gameweek {inputs.deadline.gameweek}; {scored_note}"
        )
        if arguments.dry_run:
            print("Dry run: nothing written.")
            return 0

        panel = build_panel(Path(arguments.archive_root))
        # Members' advice uses the same projection our own decision uses; from GW2 on that
        # is the produced handoff, and the live path refuses one built from another
        # capture — so the league tree and the decision cannot silently disagree.
        in_season = (
            read_projection_handoff(arguments.in_season_projection)
            if arguments.in_season_projection
            else None
        )
        projection = project(inputs, panel, in_season=in_season)
        mode_paths = None
        if arguments.mode_residuals:
            history = load_residual_history(arguments.mode_residuals)
            mode_paths = build_mode_paths(
                projection,
                history,
                season=season,
                gameweek=int(inputs.deadline.gameweek),
            )
            print(
                f"mode paths: {mode_paths.config.scenario_count} scenarios for gameweek "
                f"{inputs.deadline.gameweek} from {history.source_id}"
            )
        out_dir = Path(arguments.out) / "data" / "league"
        with ExitStack() as stack:
            mapper: Callable[..., Iterable[MemberRender]] = map
            if arguments.workers > 1:
                executor = stack.enter_context(
                    ProcessPoolExecutor(
                        max_workers=arguments.workers,
                        mp_context=multiprocessing.get_context("spawn"),
                        initializer=_worker_init,
                        initargs=(
                            str(snapshot_root),
                            snapshot_id,
                            season,
                            (
                                str(arguments.in_season_projection)
                                if arguments.in_season_projection
                                else None
                            ),
                            str(arguments.archive_root),
                        ),
                    )
                )
                mapper = pool_mapper(executor)
            report = build_league_views(
                CapturePicksProvider(snapshot, snapshot_id),
                registry.entries,
                inputs,
                projection,
                read_season_rules(snapshot, season=season),
                league_id=arguments.league,
                league_name=league_name,
                out_dir=out_dir,
                standings=standings,
                scored_gameweek=scored,
                mode_paths=mode_paths,
                rival_menu=not arguments.no_rival_menu,
                mapper=mapper,
                # The saf-puan three- and five-week windows, from the same capture and
                # handoff the one-week advice reads.
                horizon_builder=member_horizon_builder(
                    snapshot, season=season, panel=panel, in_season=in_season
                ),
                # Written by the same call that writes the published bytes, because this
                # publish re-solves in a fresh worktree at whatever code is on develop:
                # only the process that emitted the advice can record what it emitted.
                advice_record_root=(
                    None if arguments.no_advice_record else Path(arguments.advice_record_root)
                ),
            )
        print(f"Rendered {report.rendered_count} of {len(report.members)} members into {out_dir}")
        for member in report.members:
            if not member.rendered:
                print(f"  not rendered  {member.entry_id}  {member.reason}")
            elif member.reason:
                # A rendered member can still carry a note — competitive modes that did
                # not price, or a name the publisher had to normalise, truncate or refuse.
                # Printing it is the only place an operator learns that a published name
                # is not byte-for-byte what the capture held.
                print(f"  note          {member.entry_id}  {member.reason}")
        menu_files = sum(1 for name in report.files if "/vs-" in name)
        window_files = sum(1 for name in report.files if name.endswith(("/3.json", "/5.json")))
        print(
            f"Wrote {len(report.files)} files, {menu_files} of them rival-menu entries and "
            f"{window_files} of them multi-week windows"
        )
        return 0
    except AdviceRecordConflictError as error:
        # The published files are already on disk; only the record refused. Name the
        # escape, because the alternative to naming it is an operator improvising one
        # against a deadline — and every improvisation here loses evidence.
        print(
            f"build_league_site refused:\n  {error}\n"
            "  This is one capture rebuilt into different advice, not a second publish and "
            "not a re-run at a later minute: a publish from a fresh capture writes its own "
            "record, and a re-publish of this one that says the same thing is a replay. "
            "Both are accepted. So the difference above came from our own code, and it is "
            "worth a minute before "
            "the deadline. If the deadline will not wait, re-run with --no-advice-record "
            "(scripts.publish_gameweek_site takes the same flag and passes it through): the "
            "recorded capture is kept as it stands and the difference above is what to "
            "reconcile afterwards.",
            file=sys.stderr,
        )
        return 1
    except (DataError, OSError, ValueError) as error:
        print(f"build_league_site failed:\n  {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

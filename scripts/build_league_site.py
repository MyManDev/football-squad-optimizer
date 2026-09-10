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
import sys
from dataclasses import replace
from pathlib import Path

from squadopt.application.advice_record import AdviceRecordConflictError
from squadopt.application.league_publication import (
    LeaguePublicationRequest,
    ModePathsSummary,
    PreparedLeaguePublication,
    prepare_league_publication,
    publish_prepared_league,
)
from squadopt.application.league_publication import (
    last_scored_gameweek as last_scored_gameweek,
)
from squadopt.application.league_publication import (
    member_points as member_points,
)
from squadopt.application.league_publication import (
    resolve_live_snapshot_id as resolve_live_snapshot_id,
)
from squadopt.data.errors import DataError
from squadopt.platform.capture_context import CapturePicksProvider as CapturePicksProvider
from squadopt.platform.publication_workers import (
    _render_in_worker as _render_in_worker,
)
from squadopt.platform.publication_workers import (
    _worker_init as _worker_init,
)
from squadopt.platform.publication_workers import (
    league_mapper,
)
from squadopt.platform.publication_workers import (
    pool_mapper as pool_mapper,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_ROOT = REPOSITORY_ROOT / "data" / "snapshots"
ARCHIVE_ROOT = REPOSITORY_ROOT / "data" / "raw" / "vaastav-fpl"
REGISTRY_PATH = REPOSITORY_ROOT / "data" / "entries" / "registry.json"
#: Where the immutable per-member, per-gameweek advice record lands. Local like the
#: captures and the registry: it names identifiable people's squads, so ``.gitignore``
#: keeps it out of the repository for the same reason ``data/entries/`` is out.
ADVICE_RECORD_ROOT = REPOSITORY_ROOT / "data" / "advice_records"


def _capture_note(prepared: PreparedLeaguePublication) -> None:
    scored = prepared.scored_gameweek
    scored_note = (
        f"points for {prepared.scored_members} of {len(prepared.registrations)} "
        f"from gameweek {scored}"
        if scored is not None
        else "no scored gameweek yet, so no points are published"
    )
    print(
        f"capture {prepared.request.snapshot_id}: {len(prepared.registrations)} registered, "
        f"{len(prepared.standings)} in the standings, targeting {prepared.season} "
        f"gameweek {prepared.inputs.deadline.gameweek}; {scored_note}"
    )


def _mode_note(summary: ModePathsSummary) -> None:
    print(
        f"mode paths: {summary.scenario_count} scenarios for gameweek "
        f"{summary.gameweek} from {summary.source_id}"
    )


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
        request = LeaguePublicationRequest(
            snapshot_root=snapshot_root,
            snapshot_id=snapshot_id,
            archive_root=Path(arguments.archive_root),
            registry_path=Path(arguments.registry),
            out_dir=Path(arguments.out),
            league_id=arguments.league,
            season=arguments.season,
            handoff_path=arguments.in_season_projection,
            mode_residuals=arguments.mode_residuals,
            record_root=None if arguments.no_advice_record else Path(arguments.advice_record_root),
            history_record_root=Path(arguments.advice_record_root),
            rival_menu=not arguments.no_rival_menu,
        )
        prepared = prepare_league_publication(request)
        _capture_note(prepared)
        if arguments.dry_run:
            print("Dry run: nothing written.")
            return 0
        with league_mapper(replace(request, season=prepared.season), arguments.workers) as mapper:
            result = publish_prepared_league(prepared, mapper=mapper, on_mode_paths=_mode_note)
        report = result.report
        out_dir = request.out_dir / "data" / "league"
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
        # A member this run did not render must not keep the last publish's document: the
        # tree is checked out of origin/develop and committed as a union, so leaving it
        # would serve a finished gameweek's advice under this week's league.
        for path in report.removed:
            print(f"  removed       {path}  (not produced by this run)")
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

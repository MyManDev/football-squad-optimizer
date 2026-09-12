"""Write the frontend's static data tree from the season ledger.

    python -m scripts.build_site --season 2026-27 --out web/public
    python -m scripts.build_site --schema-only

Thin shell over ``squadopt.application.build_site``: it reads the captures and the
ledger, makes the same tick plan ``run_season_tick --dry-run`` would make (so the status
page says what the scheduler would do), and writes ``<out>/data/**``. It records nothing
and never plans a real action.
"""

import argparse
import sys
from pathlib import Path

from squadopt.application import UI_VIEW_SCHEMA_PATH, write_ui_view_schema
from squadopt.application import (
    TickRequest as TickRequest,
)
from squadopt.application import (
    build_site as build_site,
)
from squadopt.application import (
    plan_season_tick as plan_season_tick,
)
from squadopt.application.site_publication import (
    SitePublicationRequest,
    SiteSeasonUnavailableError,
    publish_site,
)
from squadopt.data.errors import DataError
from squadopt.live import LedgerError

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HANDOFF_ROOT = REPOSITORY_ROOT / "data" / "handoffs"
DEFAULT_LOG_ROOT = REPOSITORY_ROOT / "data" / "logs"


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", default=None, help="season to render (default: inferred)")
    parser.add_argument("--ledger-root", type=Path, default=REPOSITORY_ROOT / "data" / "ledger")
    parser.add_argument(
        "--snapshot-root", type=Path, default=REPOSITORY_ROOT / "data" / "snapshots"
    )
    parser.add_argument("--handoff-root", type=Path, default=DEFAULT_HANDOFF_ROOT)
    parser.add_argument("--log-root", type=Path, default=DEFAULT_LOG_ROOT)
    parser.add_argument("--out", type=Path, default=REPOSITORY_ROOT / "web" / "public")
    parser.add_argument(
        "--horizon-manifest",
        type=Path,
        help="verified H1/H3/H5 batch manifest to attach as non-decision evidence",
    )
    parser.add_argument("--now", help="pretend it is this UTC instant (replay / tests)")
    parser.add_argument("--no-status", action="store_true", help="skip the tick plan / status.json")
    parser.add_argument(
        "--no-league", action="store_true", help="skip league.json (no capture is read)"
    )
    parser.add_argument(
        "--schema-only", action="store_true", help=f"only (re)write {UI_VIEW_SCHEMA_PATH}"
    )
    return parser.parse_args()


def main() -> int:
    arguments = _parse_arguments()
    if arguments.schema_only:
        print(f"Wrote {write_ui_view_schema()}")
        return 0
    try:
        result = publish_site(
            SitePublicationRequest(
                snapshot_root=arguments.snapshot_root,
                ledger_root=arguments.ledger_root,
                archive_root=REPOSITORY_ROOT / "data" / "raw" / "vaastav-fpl",
                handoff_root=arguments.handoff_root,
                summary_root=REPOSITORY_ROOT / "docs",
                log_root=arguments.log_root,
                out_dir=arguments.out,
                season=arguments.season,
                now_utc=arguments.now,
                include_status=not arguments.no_status,
                include_league=not arguments.no_league,
                horizon_manifest=arguments.horizon_manifest,
            )
        )
        report = result.report
    except SiteSeasonUnavailableError as error:
        print(str(error))
        return 1
    except (DataError, LedgerError) as error:
        print(f"Could not build the site:\n  {error}")
        return 1
    horizon_note = (
        f"; horizon evidence GW{report.horizon_evidence_gameweek}"
        if report.horizon_evidence_gameweek is not None
        else ""
    )
    kept_note = (
        "; ledger.json kept from the published tree" if report.ledger_kept_from_published else ""
    )
    print(
        f"Wrote {len(report.files)} files under {report.out_dir / 'data'} for {report.season}: "
        f"gameweeks {list(report.decided_gameweeks)} (settled {list(report.settled_gameweeks)})"
        f"{'; status.json' if report.status_written else ''}"
        f"{'; league.json' if report.league_written else ''}"
        f"{horizon_note}"
        f"{kept_note}"
    )
    write_ui_view_schema()
    return 0


if __name__ == "__main__":
    sys.exit(main())

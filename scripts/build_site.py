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
from datetime import UTC, datetime
from pathlib import Path

from scripts.run_season_tick import DEFAULT_HANDOFF_ROOT, DEFAULT_LOG_ROOT, _plan

from squadopt.application import UI_VIEW_SCHEMA_PATH, build_site, write_ui_view_schema
from squadopt.data.errors import DataError
from squadopt.data.snapshots import list_snapshot_ids, read_snapshot
from squadopt.live import LedgerError
from squadopt.live.tick import TickConfig

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


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
    now_utc = arguments.now or datetime.now(UTC).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )
    plan = None
    season = arguments.season
    try:
        if not arguments.no_status:
            plan = _plan(
                argparse.Namespace(
                    snapshot_root=arguments.snapshot_root,
                    ledger_root=arguments.ledger_root,
                    handoff_root=arguments.handoff_root,
                    season=arguments.season,
                ),
                now_utc,
                TickConfig(),
            )
            season = season or plan.season
        if season is None:
            print("Season could not be inferred; pass --season.")
            return 1
        snapshot = None
        if not arguments.no_league:
            identifiers = list_snapshot_ids(arguments.snapshot_root)
            if identifiers:
                snapshot = read_snapshot(arguments.snapshot_root, identifiers[-1])
        report = build_site(
            ledger_root=arguments.ledger_root,
            season=str(season),
            out_dir=arguments.out,
            plan=plan,
            runlog_root=arguments.log_root,
            snapshot=snapshot,
            now=datetime.fromisoformat(now_utc.replace("Z", "+00:00")),
        )
    except (DataError, LedgerError) as error:
        print(f"Could not build the site:\n  {error}")
        return 1
    print(
        f"Wrote {len(report.files)} files under {report.out_dir / 'data'} for {report.season}: "
        f"gameweeks {list(report.decided_gameweeks)} (settled {list(report.settled_gameweeks)})"
        f"{'; status.json' if report.status_written else ''}"
        f"{'; league.json' if report.league_written else ''}"
    )
    write_ui_view_schema()
    return 0


if __name__ == "__main__":
    sys.exit(main())

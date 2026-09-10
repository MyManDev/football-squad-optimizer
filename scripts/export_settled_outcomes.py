"""Compatibility command for squadopt.application.settled_outcomes."""

import argparse
import sys
from pathlib import Path

from scripts._experiment_cli import _git_revision, write_json, write_text

from squadopt.application.settled_outcomes import (
    DEFAULT_OUTPUT_DIR as DEFAULT_OUTPUT_DIR,
)
from squadopt.application.settled_outcomes import (
    DEFAULT_RECORD as DEFAULT_RECORD,
)
from squadopt.application.settled_outcomes import (
    DEFAULT_SNAPSHOT_ROOT as DEFAULT_SNAPSHOT_ROOT,
)
from squadopt.application.settled_outcomes import (
    DEFAULT_SUMMARY as DEFAULT_SUMMARY,
)
from squadopt.application.settled_outcomes import (
    SettledOutcomeExportError as SettledOutcomeExportError,
)
from squadopt.application.settled_outcomes import (
    _canonical as _canonical,
)
from squadopt.application.settled_outcomes import (
    _Capture as _Capture,
)
from squadopt.application.settled_outcomes import (
    _captures as _captures,
)
from squadopt.application.settled_outcomes import (
    _deadline as _deadline,
)
from squadopt.application.settled_outcomes import (
    _multiplier as _multiplier,
)
from squadopt.application.settled_outcomes import (
    _Pair as _Pair,
)
from squadopt.application.settled_outcomes import (
    _publish as _publish,
)
from squadopt.application.settled_outcomes import (
    _temporary as _temporary,
)
from squadopt.application.settled_outcomes import (
    _week_summary as _week_summary,
)
from squadopt.application.settled_outcomes import (
    pair_captures as pair_captures,
)
from squadopt.application.settled_outcomes import (
    summary as summary,
)
from squadopt.application.settled_outcomes import (
    table_name as table_name,
)
from squadopt.application.settled_outcomes import (
    write_artifact as write_artifact,
)
from squadopt.data.errors import DataSourceError
from squadopt.data.sources.fpl_live import (
    availability_snapshot,
    live_event_outcomes,
    live_payload,
)
from squadopt.features.settled_outcomes import (
    ARTIFACT_CONTRACT_VERSION,
    CONTRACT_VERSION,
    build_settled_outcomes,
    read_settled_outcomes_artifact,
)


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", required=True, help="The season these gameweeks belong to.")
    parser.add_argument("--snapshot-root", type=Path, default=DEFAULT_SNAPSHOT_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_RECORD)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Write nothing; print which gameweeks are available and which are not.",
    )
    return parser.parse_args()


def main() -> int:
    arguments = _parse_arguments()
    if not arguments.snapshot_root.is_dir():
        print(f"No snapshot directory at {arguments.snapshot_root}.")
        return 1

    try:
        captures = _captures(arguments.snapshot_root)
        pairs, skipped = pair_captures(captures)
    except (DataSourceError, SettledOutcomeExportError) as error:
        print(f"Refused: {error}")
        return 1

    print(f"Read {len(captures)} live capture(s) under {arguments.snapshot_root}.")
    for pair in pairs:
        print(
            f"  gw{pair.gameweek:02d}  settled {pair.settled.snapshot_id}  "
            f"pre-deadline {pair.pre_deadline.snapshot_id}"
        )
    for reason in skipped:
        print(f"  skipped  {reason}")
    if not pairs:
        print("No settled gameweek has both captures on disk; nothing to accumulate.")
        return 1
    if arguments.dry_run:
        print("Dry run: nothing was written.")
        return 0

    revision, dirty = _git_revision()
    if dirty:
        print(
            "Refused: the working tree is dirty, so repository_commit would not reproduce "
            "this artifact. Commit or stash first."
        )
        return 1

    weeks: list[dict[str, object]] = []
    for pair in pairs:
        availability = availability_snapshot(pair.pre_deadline.bootstrap)
        outcomes = live_event_outcomes(
            pair.settled.payloads[live_payload(pair.gameweek)],
            pair.settled.bootstrap,
            gameweek=pair.gameweek,
        )
        table = build_settled_outcomes(
            outcomes,
            availability,
            _multiplier(availability),
            season=arguments.season,
            gameweek=pair.gameweek,
        )
        name = table_name(arguments.season, pair)
        manifest = write_artifact(
            table,
            arguments.output_dir,
            name,
            pair=pair,
            season=arguments.season,
            repository_commit=revision,
        )
        # Read it back through the contract check before it is summarised. An artifact that
        # its own reader rejects is not one anybody should be told about.
        read_settled_outcomes_artifact(
            arguments.output_dir / f"{name}.csv",
            arguments.output_dir / f"{name}.manifest.json",
        )
        weeks.append(_week_summary(table, manifest, pair))
        print(f"  wrote    {name}.csv  {manifest['row_count']} rows")

    record: dict[str, object] = {
        "artifact_type": "settled_outcomes",
        "contract_version": CONTRACT_VERSION,
        "artifact_contract_version": ARTIFACT_CONTRACT_VERSION,
        "season": arguments.season,
        "gameweeks_exported": len(weeks),
        "gameweeks_skipped": len(skipped),
        "skipped": list(skipped),
        "gameweeks": weeks,
        "gate_evidence": False,
        "measurement_only": True,
        "locked_holdout_accessed": False,
    }
    write_json(arguments.json_output, record)
    write_text(arguments.markdown_output, summary(record))
    print(f"Wrote {arguments.json_output}")
    print(f"Wrote {arguments.markdown_output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

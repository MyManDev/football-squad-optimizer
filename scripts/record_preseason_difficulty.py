"""Pin what the platform published about a season's fixtures before it started.

    python -m scripts.record_preseason_difficulty --season 2026-27

The opponent projection study found the largest fixture effect this programme has measured
— about +1.74 realized points a gameweek — and ruled it inadmissible, because the archive's
difficulty rating tracks the season it describes better than the season before it. The
archive cannot settle that. A live season can, but only from a capture taken before the
first ball is kicked, and that evidence expires the moment the season starts.

This writes the record. Give it ``--compare <snapshot-id>`` later in the season, or once the
archive carries the finished season, and it also reports whether the published difficulty
has moved since — which is the measurement the record exists for.
"""

import argparse
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

from scripts._experiment_cli import REPOSITORY_ROOT, artifact_metadata, write_json, write_text

from squadopt.data.errors import DataSourceError
from squadopt.data.snapshots import list_snapshot_ids
from squadopt.experiments import ExperimentError
from squadopt.experiments.preseason_difficulty import (
    build_preseason_record,
    compare_to_later,
    drift_to_dict,
    record_to_dict,
    record_to_markdown,
)

LOGGER = logging.getLogger(__name__)
DEFAULT_SNAPSHOT_ROOT = REPOSITORY_ROOT / "data" / "snapshots"


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-root", type=Path, default=DEFAULT_SNAPSHOT_ROOT)
    parser.add_argument(
        "--snapshot-id",
        default=None,
        help="Capture to record. Defaults to the earliest stored capture, which is the one "
        "most likely to precede the first kickoff.",
    )
    parser.add_argument("--season", default="2026-27")
    parser.add_argument(
        "--compare",
        default=None,
        help="A later capture to check the recorded difficulty against.",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "preseason_fixture_difficulty.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "preseason_fixture_difficulty.md",
    )
    return parser.parse_args()


def main() -> int:
    arguments = _parse_arguments()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    root = Path(arguments.snapshot_root)
    if not root.is_dir():
        print(f"No snapshot store at {root}.")
        return 1
    created_utc = datetime.now(UTC).isoformat(timespec="seconds")
    try:
        stored = list_snapshot_ids(root)
        if not stored:
            print(f"No captures stored under {root}.")
            return 1
        snapshot_id = str(arguments.snapshot_id or stored[0])
        LOGGER.info("Recording %s for %s", snapshot_id, arguments.season)
        record = build_preseason_record(root, snapshot_id, season=str(arguments.season))
        drift = None
        if arguments.compare:
            later = build_preseason_record(
                root, str(arguments.compare), season=str(arguments.season)
            )
            drift = compare_to_later(record, later.difficulty)
            LOGGER.info(
                "Compared against %s: %d of %d fixture sides changed",
                arguments.compare,
                drift.changed_rows,
                drift.compared_rows,
            )
    except (DataSourceError, ExperimentError) as error:
        print(f"Could not record the pre-season difficulty:\n  {error}")
        return 1
    document = {
        **artifact_metadata(panel_rows=0, created_utc=created_utc),
        **record_to_dict(record),
        "compared_against": str(arguments.compare) if arguments.compare else None,
        "drift": drift_to_dict(drift) if drift is not None else None,
        "measurement_only": True,
        "locked_holdout_accessed": False,
    }
    markdown = record_to_markdown(record, drift)
    write_json(arguments.json_output, document)
    write_text(arguments.markdown_output, markdown)
    print(markdown)
    print(f"Wrote {arguments.json_output}")
    print(f"Wrote {arguments.markdown_output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

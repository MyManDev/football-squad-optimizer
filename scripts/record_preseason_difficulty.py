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
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

from scripts._experiment_cli import REPOSITORY_ROOT, artifact_metadata, write_json, write_text

from squadopt.data.errors import DataSourceError
from squadopt.data.snapshots import list_snapshot_ids
from squadopt.data.sources import FPL_LIVE_SOURCE
from squadopt.experiments import ExperimentError
from squadopt.experiments.preseason_difficulty import (
    build_preseason_record,
    compare_to_later,
    drift_to_dict,
    later_difficulty,
    record_from_dict,
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
        help="Capture to record. Defaults to the earliest live capture stored, which is the "
        "one most likely to precede the first kickoff.",
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


def _stored_record(path: Path) -> dict[str, object] | None:
    if not Path(path).is_file():
        return None
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    return document if isinstance(document, dict) else None


def _readings(document: dict[str, object] | None) -> list[dict[str, object]]:
    """Every drift reading the stored record already holds, the single older one included."""

    if document is None:
        return []
    held = document.get("readings")
    if isinstance(held, list):
        return [dict(row) for row in held if isinstance(row, dict)]
    drift = document.get("drift")
    compared = document.get("compared_against")
    if isinstance(drift, dict) and isinstance(compared, str):
        # Written before readings were kept as a list. The capture's instant was not stored,
        # and its identifier carries it.
        stamp = compared.split("-")[2]
        instant = (
            f"{stamp[0:4]}-{stamp[4:6]}-{stamp[6:8]}T{stamp[9:11]}:{stamp[11:13]}:{stamp[13:15]}Z"
        )
        return [{"snapshot_id": compared, "captured_at_utc": instant, **drift}]
    return []


def main() -> int:
    arguments = _parse_arguments()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    root = Path(arguments.snapshot_root)
    if not root.is_dir():
        print(f"No snapshot store at {root}.")
        return 1
    created_utc = datetime.now(UTC).isoformat(timespec="seconds")
    try:
        if arguments.snapshot_id is not None:
            snapshot_id = str(arguments.snapshot_id)
        else:
            # The earliest *live* capture, which is the mirror image of the "last entry"
            # bug: several collectors share this root and an identifier begins with its
            # source, so a lexical listing orders by collector before capture time, and
            # `fpl-elite-picks` sorts *before* `fpl-live`. Taking the first entry of an
            # unfiltered listing therefore returns whichever elite-picks capture exists,
            # however recent — the opposite of the pre-season capture wanted here, and a
            # capture holding no fixture difficulty at all. Naming one with --snapshot-id
            # still reaches every capture held.
            stored = list_snapshot_ids(root, source=FPL_LIVE_SOURCE)
            if not stored:
                print(f"No {FPL_LIVE_SOURCE} captures stored under {root}.")
                return 1
            snapshot_id = stored[0]
        stored_document = _stored_record(arguments.json_output)
        if arguments.compare and stored_document is not None:
            # The record is the evidence; the capture it was made from may be gone (the
            # 2026-27 one was lost on 2026-09-10). A comparison reads the record.
            record = record_from_dict(stored_document)
            LOGGER.info("Reading the committed record of %s", record.snapshot_id)
        else:
            LOGGER.info("Recording %s for %s", snapshot_id, arguments.season)
            record = build_preseason_record(root, snapshot_id, season=str(arguments.season))
        drift = None
        readings = _readings(stored_document)
        if arguments.compare:
            compared = str(arguments.compare)
            later = later_difficulty(root, compared, season=str(arguments.season))
            drift = compare_to_later(record, later)
            readings = [row for row in readings if row["snapshot_id"] != compared]
            readings.append(
                {
                    "snapshot_id": compared,
                    "captured_at_utc": str(later["captured_at_utc"].iloc[0]),
                    **drift_to_dict(drift),
                }
            )
            readings.sort(key=lambda row: str(row["captured_at_utc"]))
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
        "readings": readings,
        "measurement_only": True,
        "locked_holdout_accessed": False,
    }
    markdown = record_to_markdown(record, drift, readings)
    write_json(arguments.json_output, document)
    write_text(arguments.markdown_output, markdown)
    print(markdown)
    print(f"Wrote {arguments.json_output}")
    print(f"Wrote {arguments.markdown_output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

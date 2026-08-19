"""Evaluate a previously frozen Sprint 2 candidate on the locked holdout."""

import argparse
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

from scripts._experiment_cli import (
    DEFAULT_ARCHIVE_ROOT,
    DEFAULT_ARTIFACT_ROOT,
    artifact_metadata,
    write_json,
    write_text,
)

from squadopt.data.sources.vaastav import ARCHIVE_COMMIT, ARCHIVE_REPOSITORY, build_panel
from squadopt.experiments import (
    ScreeningExperimentConfig,
    frozen_candidate_from_dict,
    holdout_result_to_dict,
    holdout_result_to_markdown,
    run_frozen_holdout,
)


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--frozen-candidate",
        type=Path,
        default=DEFAULT_ARTIFACT_ROOT / "frozen_candidate.json",
    )
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument(
        "--json-output",
        type=Path,
        default=DEFAULT_ARTIFACT_ROOT / "holdout.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=DEFAULT_ARTIFACT_ROOT / "holdout.md",
    )
    return parser.parse_args()


def main() -> int:
    """Load a frozen decision, evaluate holdout only, and persist the final gate."""

    arguments = _parse_arguments()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    archive_root: Path = arguments.archive_root
    frozen_path: Path = arguments.frozen_candidate
    if not archive_root.is_dir():
        print(
            f"Archive not found at {archive_root}.\n"
            "Run 'python -m scripts.fetch_historical_data' first."
        )
        return 1
    if not frozen_path.is_file():
        print(
            f"Frozen candidate not found at {frozen_path}.\n"
            "Run 'python -m scripts.run_screening_doe' first."
        )
        return 1

    payload = json.loads(frozen_path.read_text(encoding="utf-8"))
    frozen = frozen_candidate_from_dict(payload)
    created_utc = datetime.now(UTC).isoformat(timespec="seconds")
    panel = build_panel(archive_root)
    config = ScreeningExperimentConfig(
        run_metadata={
            "dataset_repository": ARCHIVE_REPOSITORY,
            "dataset_commit": ARCHIVE_COMMIT,
            "created_utc": created_utc,
        }
    )
    result = run_frozen_holdout(panel, frozen, config)
    report = {
        **artifact_metadata(panel_rows=len(panel), created_utc=created_utc),
        **holdout_result_to_dict(result),
    }
    write_json(arguments.json_output, report)
    write_text(arguments.markdown_output, holdout_result_to_markdown(result))

    print(f"Wrote holdout JSON to {arguments.json_output}")
    print(f"Wrote holdout Markdown to {arguments.markdown_output}")
    print(f"Promoted: {str(result.promoted).lower()}")
    print(result.decision_reason)
    return 0


if __name__ == "__main__":
    sys.exit(main())

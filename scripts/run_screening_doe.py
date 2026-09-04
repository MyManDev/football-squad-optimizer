"""Run development-only Sprint 2 screening and freeze exactly one candidate."""

import argparse
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
    freeze_screening_candidate,
    frozen_candidate_to_dict,
    run_screening_experiment,
    screening_result_to_dict,
    screening_result_to_markdown,
)


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument(
        "--json-output",
        type=Path,
        default=DEFAULT_ARTIFACT_ROOT / "screening.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=DEFAULT_ARTIFACT_ROOT / "screening.md",
    )
    parser.add_argument(
        "--frozen-output",
        type=Path,
        default=DEFAULT_ARTIFACT_ROOT / "frozen_candidate.json",
    )
    return parser.parse_args()


def main() -> int:
    """Run only development seasons and persist the frozen holdout input."""

    arguments = _parse_arguments()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    archive_root: Path = arguments.archive_root
    if not archive_root.is_dir():
        print(
            f"Archive not found at {archive_root}.\n"
            "Run 'python -m scripts.fetch_historical_data' first."
        )
        return 1

    created_utc = datetime.now(UTC).isoformat(timespec="seconds")
    panel = build_panel(archive_root)
    config = ScreeningExperimentConfig(
        run_metadata={
            "dataset_repository": ARCHIVE_REPOSITORY,
            "dataset_commit": ARCHIVE_COMMIT,
            "created_utc": created_utc,
        }
    )
    result = run_screening_experiment(panel, config)
    frozen = freeze_screening_candidate(result)
    report = {
        **artifact_metadata(panel_rows=len(panel), created_utc=created_utc),
        **screening_result_to_dict(result),
    }
    markdown = screening_result_to_markdown(result)
    write_json(arguments.json_output, report)
    write_text(arguments.markdown_output, markdown)
    write_json(arguments.frozen_output, frozen_candidate_to_dict(frozen))

    print(f"Wrote screening JSON to {arguments.json_output}")
    print(f"Wrote screening Markdown to {arguments.markdown_output}")
    print(f"Froze candidate at {arguments.frozen_output}")
    print(f"Selected: {result.selected_candidate.candidate_id}")
    print("Locked holdout accessed: false")
    return 0


if __name__ == "__main__":
    sys.exit(main())

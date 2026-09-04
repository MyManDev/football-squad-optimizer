"""Re-measure S1's clean-sheet clause against a baseline that could actually be known.

    python -m scripts.run_team_rating_cs_remeasure

The clause as declared in #139 pitted the rating against a logistic on the archived
difficulty column, which the Decision 1 ruling established is written after the season it
describes. This runs the pre-registered measurable form (`docs/team_rating_cs_prereg.md`):
same comparison, same threshold, the baseline replaced by a previous-season-table logistic.
It does not reopen #139's verdict. Measurement only; the locked holdout is never read.
"""

import argparse
import logging
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from scripts._experiment_cli import (
    DEFAULT_ARCHIVE_ROOT,
    REPOSITORY_ROOT,
    artifact_metadata,
    write_json,
    write_text,
)

from squadopt.experiments import ExperimentError
from squadopt.experiments.team_rating_cs import (
    CS_REMEASURE_CONTRACT_VERSION,
    CsRemeasureConfig,
    run_cs_remeasure,
    study_to_markdown,
)

LOGGER = logging.getLogger(__name__)


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--seasons", default="2020-21,2021-22,2022-23,2023-24,2024-25")
    parser.add_argument("--evaluated-seasons", default="2022-23,2023-24,2024-25")
    parser.add_argument(
        "--json-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "team_rating_cs_remeasure.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "team_rating_cs_remeasure.md",
    )
    return parser.parse_args()


def main() -> int:
    arguments = _parse_arguments()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if not arguments.archive_root.is_dir():
        print(f"Archive not found at {arguments.archive_root}.")
        return 1
    created_utc = datetime.now(UTC).isoformat(timespec="seconds")
    try:
        config = CsRemeasureConfig(
            seasons=tuple(value.strip() for value in str(arguments.seasons).split(",")),
            evaluated_seasons=tuple(
                value.strip() for value in str(arguments.evaluated_seasons).split(",")
            ),
        )
        LOGGER.info("Re-measuring the clause on %s", ", ".join(config.evaluated_seasons))
        study = run_cs_remeasure(arguments.archive_root, config)
    except ExperimentError as error:
        print(f"Could not run the re-measurement:\n  {error}")
        return 1
    document = {
        **artifact_metadata(panel_rows=0, created_utc=created_utc),
        "contract_version": CS_REMEASURE_CONTRACT_VERSION,
        "config": asdict(study.config),
        "seasons": [asdict(row) for row in study.seasons],
        "pooled_rating_brier": study.pooled_rating_brier,
        "pooled_table_brier": study.pooled_table_brier,
        "pooled_constant_brier": study.pooled_constant_brier,
        "verdict": dict(study.verdict),
        "diagnostics": dict(study.diagnostics),
        "measurement_only": True,
        "locked_holdout_accessed": False,
    }
    markdown = study_to_markdown(study)
    write_json(arguments.json_output, document)
    write_text(arguments.markdown_output, markdown)
    print(markdown)
    print(f"Wrote {arguments.json_output}")
    print(f"Wrote {arguments.markdown_output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

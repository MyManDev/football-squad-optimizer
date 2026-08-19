"""Fit a team rating from goals and judge it against the rating the platform ships.

    python -m scripts.run_team_rating_study

Stage two of the recommender programme. The schedule signal study found that the published
difficulty rating improves projection error slightly and loses points at the decision level;
this asks whether a Dixon-Coles attack and defence rating fitted to goals does better at the
three things a rating is for — predicting scorelines, calibrating clean sheets, and ordering
player outcomes. The gate was fixed before the numbers existed and is applied by the code.
Measurement only: the locked holdout is refused.
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
from squadopt.experiments.team_rating import (
    TEAM_RATING_STUDY_CONTRACT_VERSION,
    TeamRatingStudyConfig,
    run_team_rating_study,
    study_to_markdown,
)

LOGGER = logging.getLogger(__name__)


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--seasons", default="2020-21,2021-22,2022-23,2023-24,2024-25")
    parser.add_argument("--evaluated-seasons", default="2022-23,2023-24,2024-25")
    parser.add_argument("--first-evaluated-gameweek", type=int, default=6)
    parser.add_argument("--bootstrap-resamples", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--json-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "team_rating_study.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "team_rating_study.md",
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
        config = TeamRatingStudyConfig(
            seasons=tuple(value.strip() for value in str(arguments.seasons).split(",")),
            evaluated_seasons=tuple(
                value.strip() for value in str(arguments.evaluated_seasons).split(",")
            ),
            first_evaluated_gameweek=int(arguments.first_evaluated_gameweek),
            bootstrap_resamples=int(arguments.bootstrap_resamples),
            deterministic_seed=int(arguments.seed),
        )
        LOGGER.info(
            "Fitting on %s, judging %s from gameweek %d",
            ", ".join(config.seasons),
            ", ".join(config.evaluated_seasons),
            config.first_evaluated_gameweek,
        )
        study = run_team_rating_study(arguments.archive_root, config)
    except ExperimentError as error:
        print(f"Could not run the team rating study:\n  {error}")
        return 1
    document = {
        **artifact_metadata(panel_rows=0, created_utc=created_utc),
        "contract_version": TEAM_RATING_STUDY_CONTRACT_VERSION,
        "config": asdict(study.config),
        "seasons": [asdict(card) for card in study.seasons],
        "pooled": dict(study.pooled),
        "intervals": {key: list(value) for key, value in study.intervals.items()},
        "reliability": [dict(row) for row in study.reliability],
        "example_rating": dict(study.example_rating),
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

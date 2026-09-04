"""Measure an opponent-aware adjustment where the decision is actually made.

    python -m scripts.run_opponent_projection_study

Stage three of the recommender programme. The schedule signal study showed that an
adjustment can improve projection error and still lose points; the team rating study showed
that a rating fitted to goals orders players better than the published one. This puts both
instruments inside the operational control's own projection across its walk-forward folds
and judges each on accuracy, on ordering, and on the squad a CP-SAT optimizer builds from
it. The gate was fixed before the numbers existed and is applied by the code. Measurement
only: nothing under `prediction/` changes and the locked holdout is refused.
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
from squadopt.experiments.opponent_projection import (
    OPPONENT_PROJECTION_STUDY_CONTRACT_VERSION,
    OpponentProjectionConfig,
    run_opponent_projection_study,
    study_to_markdown,
)

LOGGER = logging.getLogger(__name__)


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--seasons", default="2020-21,2021-22,2022-23,2023-24,2024-25")
    parser.add_argument("--development-seasons", default="2021-22,2022-23,2023-24,2024-25")
    parser.add_argument("--evaluated-seasons", default="2022-23,2023-24,2024-25")
    parser.add_argument("--bootstrap-resamples", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--json-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "opponent_projection_study.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "opponent_projection_study.md",
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
        config = OpponentProjectionConfig(
            seasons=tuple(value.strip() for value in str(arguments.seasons).split(",")),
            development_seasons=tuple(
                value.strip() for value in str(arguments.development_seasons).split(",")
            ),
            evaluated_seasons=tuple(
                value.strip() for value in str(arguments.evaluated_seasons).split(",")
            ),
            bootstrap_resamples=int(arguments.bootstrap_resamples),
            deterministic_seed=int(arguments.seed),
        )
        LOGGER.info(
            "Judging %s on the control's folds over %s",
            ", ".join(config.evaluated_seasons),
            ", ".join(config.development_seasons),
        )
        study = run_opponent_projection_study(arguments.archive_root, config)
    except ExperimentError as error:
        print(f"Could not run the opponent projection study:\n  {error}")
        return 1
    document = {
        **artifact_metadata(panel_rows=0, created_utc=created_utc),
        "contract_version": OPPONENT_PROJECTION_STUDY_CONTRACT_VERSION,
        "config": asdict(study.config),
        "population": {season: dict(values) for season, values in study.population.items()},
        "candidates": [
            {
                "candidate": outcome.candidate,
                "coefficients": {
                    position: dict(values) for position, values in outcome.coefficients.items()
                },
                "error_improvement": outcome.error_improvement,
                "error_interval": list(outcome.error_interval),
                "per_season_error_improvement": dict(outcome.per_season_error_improvement),
                "rank_improvement": outcome.rank_improvement,
                "per_season_rank_improvement": dict(outcome.per_season_rank_improvement),
                "decision_difference": outcome.decision_difference,
                "decision_interval": list(outcome.decision_interval),
                "per_season_decision_difference": dict(outcome.per_season_decision_difference),
                "accuracy_passes": outcome.accuracy_passes,
                "ordering_passes": outcome.ordering_passes,
                "decision_passes": outcome.decision_passes,
                "folds": [asdict(fold) for fold in outcome.folds],
            }
            for outcome in study.candidates
        ],
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

"""Measure whether a five-week window knows more than a flat projection.

    python -m scripts.run_schedule_signal_study

Two questions, one run. Does the published calendar predict a five-week window better than
repeating a player's recent rate? And does the *difficulty* inside that calendar add
anything beyond the count of fixtures? The second answer decides whether a team rating and
an opponent-aware projection are worth building. The gate was fixed before the numbers
existed and is applied by the code; this script only runs it and writes the artifact.
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
from squadopt.experiments.schedule_signal import (
    SCHEDULE_SIGNAL_STUDY_CONTRACT_VERSION,
    ScheduleSignalConfig,
    run_schedule_signal_study,
    study_to_markdown,
)

LOGGER = logging.getLogger(__name__)


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--seasons", default="2020-21,2021-22,2022-23,2023-24,2024-25")
    parser.add_argument("--evaluated-seasons", default="2022-23,2023-24,2024-25")
    parser.add_argument("--window-length", type=int, default=5)
    parser.add_argument("--origin-gameweeks", default="6,11,16,21,26,31")
    parser.add_argument("--bootstrap-resamples", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--json-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "schedule_signal_study.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "schedule_signal_study.md",
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
        config = ScheduleSignalConfig(
            seasons=tuple(value.strip() for value in str(arguments.seasons).split(",")),
            evaluated_seasons=tuple(
                value.strip() for value in str(arguments.evaluated_seasons).split(",")
            ),
            window_length=int(arguments.window_length),
            origin_gameweeks=tuple(
                int(value.strip()) for value in str(arguments.origin_gameweeks).split(",")
            ),
            bootstrap_resamples=int(arguments.bootstrap_resamples),
            deterministic_seed=int(arguments.seed),
        )
        LOGGER.info(
            "Walking %s forward, judging %s over %d-gameweek windows",
            ", ".join(config.seasons),
            ", ".join(config.evaluated_seasons),
            config.window_length,
        )
        study = run_schedule_signal_study(arguments.archive_root, config)
    except ExperimentError as error:
        print(f"Could not run the schedule signal study:\n  {error}")
        return 1
    document = {
        **artifact_metadata(panel_rows=0, created_utc=created_utc),
        "contract_version": SCHEDULE_SIGNAL_STUDY_CONTRACT_VERSION,
        "config": asdict(study.config),
        "population": {season: dict(values) for season, values in study.population.items()},
        "rules": [
            {
                "rule": rule.rule,
                "pooled_rows": rule.pooled_rows,
                "pooled_mean_absolute_error": rule.pooled_mean_absolute_error,
                "pooled_rank_correlation": rule.pooled_rank_correlation,
                "coefficients": {
                    position: dict(values) for position, values in rule.coefficients.items()
                },
                "seasons": [asdict(season) for season in rule.seasons],
            }
            for rule in study.rules
        ],
        "comparisons": [
            {
                "rule": comparison.rule,
                "reference": comparison.reference,
                "rows": comparison.rows,
                "error_improvement": comparison.error_improvement,
                "error_interval": list(comparison.error_interval),
                "per_season_error_improvement": dict(comparison.per_season_error_improvement),
                "rank_improvement": comparison.rank_improvement,
                "per_season_rank_improvement": dict(comparison.per_season_rank_improvement),
                "interval_excludes_zero": comparison.interval_excludes_zero,
                "sign_consistent": comparison.sign_consistent,
                "ordering_not_worse": comparison.ordering_not_worse,
            }
            for comparison in study.comparisons
        ],
        "decisions": [asdict(decision) for decision in study.decisions],
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

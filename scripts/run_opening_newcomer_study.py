"""Measure what the opening deadline knows about players the model has never seen.

    python -m scripts.run_opening_newcomer_study

A third of an opening pool has no prior record and is projected by price alone. This walks
the development seasons forward — every judged season predicted only by seasons before it —
and asks whether ownership, the game's own expected points, and the opening fixture beat
price, in accuracy, in ordering, and in the squad the optimizer actually builds. The gate
was fixed before the numbers existed and is applied by the code; this script only runs it
and writes the artifact. Measurement only: the locked holdout is refused.
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
from squadopt.experiments.opening_newcomers import (
    OPENING_NEWCOMER_STUDY_CONTRACT_VERSION,
    OpeningStudyConfig,
    run_opening_newcomer_study,
    study_to_markdown,
)

LOGGER = logging.getLogger(__name__)


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--seasons", default="2020-21,2021-22,2022-23,2023-24,2024-25")
    parser.add_argument("--evaluated-seasons", default="2022-23,2023-24,2024-25")
    parser.add_argument("--bootstrap-resamples", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--json-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "opening_newcomer_study.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "opening_newcomer_study.md",
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
        config = OpeningStudyConfig(
            seasons=tuple(s.strip() for s in str(arguments.seasons).split(",")),
            evaluated_seasons=tuple(s.strip() for s in str(arguments.evaluated_seasons).split(",")),
            bootstrap_resamples=int(arguments.bootstrap_resamples),
            deterministic_seed=int(arguments.seed),
        )
        LOGGER.info(
            "Walking %s forward, judging %s",
            ", ".join(config.seasons),
            ", ".join(config.evaluated_seasons),
        )
        study = run_opening_newcomer_study(arguments.archive_root, config)
    except ExperimentError as error:
        print(f"Could not run the opening newcomer study:\n  {error}")
        return 1
    document = {
        **artifact_metadata(panel_rows=0, created_utc=created_utc),
        "contract_version": OPENING_NEWCOMER_STUDY_CONTRACT_VERSION,
        "config": asdict(study.config),
        "population": {season: dict(values) for season, values in study.population.items()},
        "control": dict(study.control),
        "candidates": [
            {
                "candidate": candidate.candidate,
                "features": list(candidate.features),
                "multiplier": candidate.multiplier,
                "pooled_rows": candidate.pooled_rows,
                "pooled_error_improvement": candidate.pooled_error_improvement,
                "pooled_error_interval": list(candidate.pooled_error_interval),
                "improves_every_season": candidate.improves_every_season,
                "ranks_better_every_season": candidate.ranks_better_every_season,
                "coefficients": {
                    position: dict(values) for position, values in candidate.coefficients.items()
                },
                "seasons": [asdict(season) for season in candidate.seasons],
            }
            for candidate in study.candidates
        ],
        "decisions": {
            name: [asdict(comparison) for comparison in comparisons]
            for name, comparisons in study.decisions.items()
        },
        "movers": asdict(study.movers),
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

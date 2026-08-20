"""Can a Gaussian process price the rest of the season better than four constants?

    python -m scripts.run_terminal_value_study

Phase 4's first, deliberately small test, pre-registered in
`docs/terminal_value_prereg.md` before anything was fitted: from the committed
season-chain artifacts, predict the net points still to come from the mid-season squad
state, leave-one-season-out, against the constants-plus-average baseline the planner
already implies. The gate is applied by the code. Measurement only; nothing consumes the
fitted value, and the locked holdout is never read.
"""

import argparse
import logging
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from scripts._experiment_cli import REPOSITORY_ROOT, artifact_metadata, write_json, write_text

from squadopt.experiments import ExperimentError
from squadopt.experiments.terminal_value import (
    TERMINAL_VALUE_STUDY_CONTRACT_VERSION,
    TerminalValueConfig,
    run_terminal_value_study,
    study_to_markdown,
)

LOGGER = logging.getLogger(__name__)


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", type=Path, default=REPOSITORY_ROOT / "artifacts")
    parser.add_argument("--seasons", default="2021-22,2022-23,2023-24,2024-25")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--json-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "terminal_value_study.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "terminal_value_study.md",
    )
    return parser.parse_args()


def main() -> int:
    arguments = _parse_arguments()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if not arguments.artifact_root.is_dir():
        print(f"No artifact store at {arguments.artifact_root}.")
        return 1
    created_utc = datetime.now(UTC).isoformat(timespec="seconds")
    try:
        config = TerminalValueConfig(
            seasons=tuple(value.strip() for value in str(arguments.seasons).split(",")),
            deterministic_seed=int(arguments.seed),
        )
        LOGGER.info("Leave-one-season-out over %s", ", ".join(config.seasons))
        study = run_terminal_value_study(arguments.artifact_root, config)
    except ExperimentError as error:
        print(f"Could not run the terminal value study:\n  {error}")
        return 1
    document = {
        **artifact_metadata(panel_rows=0, created_utc=created_utc),
        "contract_version": TERMINAL_VALUE_STUDY_CONTRACT_VERSION,
        "config": asdict(study.config),
        "rows": study.rows,
        "seasons": [asdict(score) for score in study.seasons],
        "pooled_gp_mae": study.pooled_gp_mae,
        "pooled_baseline_mae": study.pooled_baseline_mae,
        "by_phase": {key: dict(value) for key, value in study.by_phase.items()},
        "kernel": study.kernel,
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

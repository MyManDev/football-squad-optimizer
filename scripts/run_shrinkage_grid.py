"""Measure whether decision-side projection shrinkage improves realized squads.

    python -m scripts.run_shrinkage_grid

The selection-optimism profile located the winner's curse at the top of the
projection ranking. Proportional shrinkage toward position means attacks exactly
that region without touching the prediction contract. This grid answers the money
question on real folds: does the optimizer choose better squads (higher realized
mean) from shrunken projections, and at which strength?
"""

import argparse
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

from scripts._experiment_cli import (
    DEFAULT_ARCHIVE_ROOT,
    REPOSITORY_ROOT,
    artifact_metadata,
    write_json,
    write_text,
)

from squadopt.bayesopt import BayesianCandidate
from squadopt.data.sources.vaastav import build_panel
from squadopt.experiments import (
    SHRINKAGE_RULE_VERSION,
    BaselinePolicyObjective,
    ExperimentError,
    PolicyObjectiveConfig,
)

LOGGER = logging.getLogger(__name__)
SHRINKAGE_GRID_CONTRACT_VERSION = "projection_shrinkage_grid_v1"


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--form-windows", default="5,6,10")
    parser.add_argument("--shrinkage-levels", default="0.0,0.1,0.2,0.3,0.5")
    parser.add_argument("--bench-weight", type=float, default=0.0)
    parser.add_argument(
        "--json-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "shrinkage_grid.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "shrinkage_grid.md",
    )
    return parser.parse_args()


def main() -> int:
    arguments = _parse_arguments()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if not arguments.archive_root.is_dir():
        print(f"Archive not found at {arguments.archive_root}.")
        return 1

    created_utc = datetime.now(UTC).isoformat(timespec="seconds")
    panel = build_panel(arguments.archive_root)
    form_windows = tuple(int(value) for value in str(arguments.form_windows).split(","))
    levels = tuple(float(value) for value in str(arguments.shrinkage_levels).split(","))
    if 0.0 not in levels:
        print("shrinkage-levels must include the 0.0 baseline.")
        return 1

    cells: list[dict[str, object]] = []
    try:
        for level in levels:
            objective = BaselinePolicyObjective(
                panel, PolicyObjectiveConfig(projection_shrinkage=level)
            )
            for form_window in form_windows:
                LOGGER.info("Evaluating fw=%s shrinkage=%.2f", form_window, level)
                candidate = BayesianCandidate(
                    {"form_window": form_window, "bench_weight": arguments.bench_weight}
                )
                value = objective(candidate, objective.development_fold_ids)
                cells.append(
                    {
                        "form_window": form_window,
                        "projection_shrinkage": level,
                        "mean_realized_squad_points": value,
                        "objective_configuration_fingerprint": (
                            objective.config.configuration_fingerprint
                        ),
                    }
                )
    except ExperimentError as error:
        print(f"Could not evaluate the shrinkage grid:\n  {error}")
        return 1

    baselines = {
        cell["form_window"]: cell["mean_realized_squad_points"]
        for cell in cells
        if cell["projection_shrinkage"] == 0.0
    }
    for cell in cells:
        baseline = baselines[cell["form_window"]]
        assert isinstance(baseline, float)
        value = cell["mean_realized_squad_points"]
        assert isinstance(value, float)
        cell["delta_vs_unshrunk"] = value - baseline

    document = {
        **artifact_metadata(panel_rows=len(panel), created_utc=created_utc),
        "contract_version": SHRINKAGE_GRID_CONTRACT_VERSION,
        "shrinkage_rule": SHRINKAGE_RULE_VERSION,
        "bench_weight": arguments.bench_weight,
        "cells": cells,
        "recommendation_only": True,
        "locked_holdout_accessed": False,
        "automatic_promotion": False,
    }

    lines = [
        "# Projection shrinkage grid",
        "",
        f"- Contract: `{SHRINKAGE_GRID_CONTRACT_VERSION}`; rule `{SHRINKAGE_RULE_VERSION}`",
        f"- 147 development folds; bench_weight={arguments.bench_weight}",
        "",
        "Does the optimizer pick better squads from shrunken projections?",
        "",
        "| form_window | shrinkage | Mean realized | Delta vs unshrunk |",
        "| ---: | ---: | ---: | ---: |",
    ]
    for cell in cells:
        lines.append(
            f"| {cell['form_window']} | {cell['projection_shrinkage']:.2f} "
            f"| {cell['mean_realized_squad_points']:.4f} "
            f"| {cell['delta_vs_unshrunk']:+.4f} |"
        )
    lines += [
        "",
        "Recommendation-only measurement: no promotion, no locked-holdout access.",
    ]
    markdown = "\n".join(lines) + "\n"

    write_json(arguments.json_output, document)
    write_text(arguments.markdown_output, markdown)
    print(markdown)
    print(f"Wrote {arguments.json_output}")
    print(f"Wrote {arguments.markdown_output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

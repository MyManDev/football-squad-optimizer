"""Measure the fw10 challenger's edge over the control season by season.

    python -m scripts.run_fw10_season_robustness

The grid and the screening run report fw10-bw0's edge as a mean over 147 pooled
folds. The deferred holdout decision deserves a sharper question: is the edge
consistent across each development season, or carried by one? Every season is
evaluated in isolation (its own objective, its own folds), challenger and control on
identical folds.
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
    DEFAULT_DEVELOPMENT_SEASONS,
    BaselinePolicyObjective,
    ExperimentError,
    PolicyObjectiveConfig,
)

LOGGER = logging.getLogger(__name__)
FW10_ROBUSTNESS_CONTRACT_VERSION = "fw10_season_robustness_v1"
CHALLENGER = {"form_window": 10, "bench_weight": 0.0}
CONTROL = {"form_window": 5, "bench_weight": 0.1}


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument(
        "--json-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "fw10_season_robustness.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "fw10_season_robustness.md",
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
    rows: list[dict[str, object]] = []
    try:
        for season in DEFAULT_DEVELOPMENT_SEASONS:
            LOGGER.info("Season %s", season)
            objective = BaselinePolicyObjective(
                panel, PolicyObjectiveConfig(development_seasons=(season,))
            )
            challenger = objective(BayesianCandidate(CHALLENGER), objective.development_fold_ids)
            control = objective(BayesianCandidate(CONTROL), objective.development_fold_ids)
            rows.append(
                {
                    "season": season,
                    "fold_count": len(objective.development_fold_ids),
                    "challenger_mean": challenger,
                    "control_mean": control,
                    "delta": challenger - control,
                }
            )
    except ExperimentError as error:
        print(f"Could not measure season robustness:\n  {error}")
        return 1

    deltas = [float(str(row["delta"])) for row in rows]
    document = {
        **artifact_metadata(panel_rows=len(panel), created_utc=created_utc),
        "contract_version": FW10_ROBUSTNESS_CONTRACT_VERSION,
        "challenger": CHALLENGER,
        "control": CONTROL,
        "seasons": rows,
        "seasons_with_positive_delta": sum(1 for delta in deltas if delta > 0),
        "mean_delta": sum(deltas) / len(deltas),
        "min_delta": min(deltas),
        "recommendation_only": True,
        "locked_holdout_accessed": False,
    }

    lines = [
        "# fw10 season robustness",
        "",
        f"- Contract: `{FW10_ROBUSTNESS_CONTRACT_VERSION}`",
        "- Challenger `fw10-bw0` vs control `fw05-bw0p1`, each season evaluated in "
        "isolation on identical folds",
        "",
        "| Season | Folds | Challenger | Control | Delta |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            f"| {row['season']} | {row['fold_count']} "
            f"| {row['challenger_mean']:.4f} | {row['control_mean']:.4f} "
            f"| {row['delta']:+.4f} |"
        )
    lines += [
        "",
        f"**{document['seasons_with_positive_delta']}/{len(rows)} seasons positive; "
        f"mean {document['mean_delta']:+.2f}, worst season "
        f"{document['min_delta']:+.2f}.**",
        "",
        "Evidence for the deferred holdout decision only; nothing is promoted and",
        "the locked holdout was not read.",
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

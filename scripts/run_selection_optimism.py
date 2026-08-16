"""Profile selection-time optimism of the deterministic optimizer on real folds.

    python -m scripts.run_selection_optimism --form-window 6 --bench-weight 0.0

On every development fold the optimizer's selected XI and captain are compared, in
residual terms, against the full roster and against projection-rank buckets. The
profile locates where the winner's curse concentrates before any correction is built.
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

from squadopt.data.sources.vaastav import build_panel
from squadopt.experiments import (
    SELECTION_OPTIMISM_CONTRACT_VERSION,
    ExperimentError,
    PolicyObjectiveConfig,
    SelectionOptimismResult,
    measure_selection_optimism,
)

LOGGER = logging.getLogger(__name__)


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--seasons", default=None, help="Comma list; default: all development")
    parser.add_argument("--form-window", type=int, default=6)
    parser.add_argument("--bench-weight", type=float, default=0.0)
    parser.add_argument(
        "--json-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "selection_optimism.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "selection_optimism.md",
    )
    return parser.parse_args()


def _markdown(result: SelectionOptimismResult) -> str:
    lines = [
        "# Selection optimism profile",
        "",
        f"- Contract: `{SELECTION_OPTIMISM_CONTRACT_VERSION}`",
        f"- Folds: {result.fold_count}; anchor form_window={result.form_window}, "
        f"bench_weight={result.bench_weight}",
        "",
        "| Population | Mean residual (realized minus projected) |",
        "| --- | ---: |",
        f"| Full roster | {result.roster_mean_residual:+.3f} |",
        f"| Selected starters | {result.starter_mean_residual:+.3f} |",
        f"| Captains | {result.captain_mean_residual:+.3f} |",
        "",
        f"**Selection gap: {result.selection_gap_per_starter:+.3f} points per starter** "
        f"(x 11 starters + doubled captain approximates the squad-level bias). "
        f"Projected XI mean {result.mean_projected_xi_score:.2f} vs realized "
        f"{result.mean_realized_xi_score:.2f}.",
        "",
        "## By projection rank (within each fold's roster)",
        "",
        "| Rank bucket | Mean residual |",
        "| --- | ---: |",
    ]
    for name, value in result.rank_bucket_mean_residuals.items():
        lines.append(f"| {name} | {value:+.3f} |")
    lines += [
        "",
        "## Selected starters by position",
        "",
        "| Position | Mean residual |",
        "| --- | ---: |",
    ]
    for position, value in result.position_starter_mean_residuals.items():
        lines.append(f"| {position} | {value:+.3f} |")
    lines += [
        "",
        "Measurement only. The profile tells a correction where to act; it does not",
        "apply one.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    arguments = _parse_arguments()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if not arguments.archive_root.is_dir():
        print(f"Archive not found at {arguments.archive_root}.")
        return 1

    created_utc = datetime.now(UTC).isoformat(timespec="seconds")
    panel = build_panel(arguments.archive_root)
    config = (
        PolicyObjectiveConfig()
        if arguments.seasons is None
        else PolicyObjectiveConfig(
            development_seasons=tuple(
                season.strip() for season in str(arguments.seasons).split(",")
            )
        )
    )
    try:
        LOGGER.info("Profiling selection optimism")
        result = measure_selection_optimism(
            panel,
            config,
            form_window=arguments.form_window,
            bench_weight=arguments.bench_weight,
        )
    except ExperimentError as error:
        print(f"Could not profile selection optimism:\n  {error}")
        return 1

    document = {
        **artifact_metadata(panel_rows=len(panel), created_utc=created_utc),
        "contract_version": SELECTION_OPTIMISM_CONTRACT_VERSION,
        "fold_count": result.fold_count,
        "form_window": result.form_window,
        "bench_weight": result.bench_weight,
        "roster_mean_residual": result.roster_mean_residual,
        "starter_mean_residual": result.starter_mean_residual,
        "captain_mean_residual": result.captain_mean_residual,
        "selection_gap_per_starter": result.selection_gap_per_starter,
        "mean_projected_xi_score": result.mean_projected_xi_score,
        "mean_realized_xi_score": result.mean_realized_xi_score,
        "rank_bucket_mean_residuals": dict(result.rank_bucket_mean_residuals),
        "position_starter_mean_residuals": dict(result.position_starter_mean_residuals),
        "diagnostics": dict(result.diagnostics),
        "measurement_only": True,
        "locked_holdout_accessed": False,
    }
    markdown = _markdown(result)
    write_json(arguments.json_output, document)
    write_text(arguments.markdown_output, markdown)
    print(markdown)
    print(f"Wrote {arguments.json_output}")
    print(f"Wrote {arguments.markdown_output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

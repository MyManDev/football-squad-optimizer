"""Run the development-only baseline versus Ridge benchmark on pinned history."""

import argparse
import json
import sys
from pathlib import Path

from squadopt.backtest import LearnedBenchmarkConfig, run_learned_benchmark
from squadopt.backtest.learned_reporting import (
    learned_benchmark_to_dict,
    learned_benchmark_to_markdown,
)
from squadopt.data.sources.vaastav import (
    ARCHIVE_COMMIT,
    ARCHIVE_REPOSITORY,
    build_panel,
)
from squadopt.prediction import RidgeProjectionConfig

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARCHIVE_ROOT = REPOSITORY_ROOT / "data" / "raw" / "vaastav-fpl"
DEFAULT_JSON_OUTPUT = REPOSITORY_ROOT / "artifacts" / "sprint6" / "learned_benchmark.json"
DEFAULT_MARKDOWN_OUTPUT = REPOSITORY_ROOT / "artifacts" / "sprint6" / "learned_benchmark.md"


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", dest="seasons", action="append")
    parser.add_argument("--form-window", type=int, default=5)
    parser.add_argument("--alpha", type=float, default=10.0)
    parser.add_argument("--min-training-rows", type=int, default=100)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    return parser.parse_args()


def main() -> int:
    """Load pinned data, execute the paired benchmark, and write both artifacts."""

    arguments = _parse_arguments()
    if not arguments.archive_root.is_dir():
        print("Historical archive is absent; run python -m scripts.fetch_historical_data first.")
        return 1
    defaults = LearnedBenchmarkConfig()
    seasons = tuple(arguments.seasons) if arguments.seasons else defaults.seasons
    panel = build_panel(arguments.archive_root)
    result = run_learned_benchmark(
        panel,
        LearnedBenchmarkConfig(
            seasons=seasons,
            ridge_config=RidgeProjectionConfig(
                form_window=arguments.form_window,
                alpha=arguments.alpha,
                min_training_rows=arguments.min_training_rows,
            ),
            run_metadata={
                "dataset_repository": ARCHIVE_REPOSITORY,
                "dataset_commit": ARCHIVE_COMMIT,
            },
        ),
    )
    report = learned_benchmark_to_dict(result)
    arguments.json_output.parent.mkdir(parents=True, exist_ok=True)
    arguments.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    arguments.json_output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    arguments.markdown_output.write_text(
        learned_benchmark_to_markdown(result),
        encoding="utf-8",
    )
    print(f"Wrote {arguments.json_output}")
    print(f"Wrote {arguments.markdown_output}")
    print(
        "Folds: "
        f"{result.decision_metrics.folds}; Ridge MAE: "
        f"{result.learned_prediction_metrics.mean_absolute_error:.4f}; paired decision delta: "
        f"{result.decision_metrics.mean_realized_points_difference}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

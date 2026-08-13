"""Run and report the leakage-safe real-data baseline benchmark.

    python -m scripts.run_baseline_benchmark
    python -m scripts.run_baseline_benchmark --season 2025-26 --form-window 5
    python -m scripts.run_baseline_benchmark --json-output benchmark.json \
        --markdown-output benchmark.md

The historical archive must first be fetched and checksum-verified with:

    python -m scripts.fetch_historical_data
"""

import argparse
import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pandas as pd

from squadopt.backtest import (
    BASELINE_BENCHMARK_CONTRACT_VERSION,
    DEFAULT_BENCHMARK_SEASONS,
    BaselineBenchmarkConfig,
    run_baseline_benchmark,
)
from squadopt.data.sources.vaastav import (
    ARCHIVE_COMMIT,
    ARCHIVE_REPOSITORY,
    SUPPORTED_SEASONS,
    build_panel,
)
from squadopt.prediction import FEATURE_GENERATION_CONTRACT_VERSION

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARCHIVE_ROOT = REPOSITORY_ROOT / "data" / "raw" / "vaastav-fpl"
MANIFEST_PATH = REPOSITORY_ROOT / "data" / "sources" / "vaastav_fpl_manifest.json"


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--season",
        dest="seasons",
        action="append",
        default=None,
        help="evaluation season; repeat to benchmark several seasons",
    )
    parser.add_argument("--form-window", type=int, default=5)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _git_revision() -> tuple[str, bool]:
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=REPOSITORY_ROOT,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"Cannot record the repository revision: {error}") from error
    return revision, dirty


def _percentile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    return float(pd.Series(values, dtype="float64").quantile(probability))


def _round_optional(value: float | None, digits: int = 6) -> float | None:
    return None if value is None else round(float(value), digits)


def _fold_records(result: Any) -> list[dict[str, object]]:
    return [
        {
            "fold_id": fold.fold_id,
            "season": fold.metadata.get("season"),
            "gameweek": fold.metadata.get("gameweek"),
            "solver_status": fold.optimization_result.solver_status.value,
            "realized_squad_points": fold.realized_squad_points,
            "projected_objective_value": fold.optimization_result.objective_value,
            "solver_runtime_seconds": fold.optimization_result.diagnostics["solve_time_seconds"],
            "squad_turnover": fold.squad_turnover,
        }
        for fold in result.folds
    ]


def _build_report(result: Any, *, panel_rows: int, created_utc: str) -> dict[str, object]:
    revision, dirty = _git_revision()
    folds = _fold_records(result)
    scores = [
        float(record["realized_squad_points"])
        for record in folds
        if record["realized_squad_points"] is not None
    ]
    statuses = Counter(str(record["solver_status"]) for record in folds)
    summary = result.summary
    optimization = result.config.optimization_config

    return {
        "created_utc": created_utc,
        "provenance": {
            "repository_commit": revision,
            "working_tree_dirty": dirty,
            "archive_repository": ARCHIVE_REPOSITORY,
            "archive_commit": ARCHIVE_COMMIT,
            "archive_manifest_sha256": _sha256(MANIFEST_PATH),
            "history_seasons": list(SUPPORTED_SEASONS),
            "history_rows": panel_rows,
            "benchmark_contract_version": BASELINE_BENCHMARK_CONTRACT_VERSION,
            "feature_generation_contract_version": FEATURE_GENERATION_CONTRACT_VERSION,
        },
        "configuration": {
            "evaluation_seasons": list(result.config.run_metadata["evaluation_seasons"]),
            "form_window": result.config.run_metadata["form_window"],
            "min_prior_gameweeks_in_season": result.config.run_metadata[
                "min_prior_gameweeks_in_season"
            ],
            "cross_season_decay": result.config.run_metadata["cross_season_decay"],
            "cross_season_min_minutes": result.config.run_metadata["cross_season_min_minutes"],
            "optimization": {
                "budget_tenths": optimization.budget_tenths,
                "squad_size": optimization.squad_size,
                "squad_position_limits": dict(optimization.squad_position_limits),
                "starting_size": optimization.starting_size,
                "starting_position_min": dict(optimization.starting_position_min),
                "starting_position_max": dict(optimization.starting_position_max),
                "max_players_per_team": optimization.max_players_per_team,
                "bench_weight": optimization.bench_weight,
                "expected_points_scale": optimization.expected_points_scale,
                "solver_time_limit_seconds": optimization.solver_time_limit_seconds,
                "deterministic_seed": optimization.deterministic_seed,
                "solver_workers": 1,
            },
        },
        "environment": {
            "platform": platform.platform(),
            "processor": platform.processor() or "unknown",
            "logical_cpu_count": os.cpu_count(),
            "python": platform.python_version(),
            "pandas": pd.__version__,
            "ortools": version("ortools"),
        },
        "summary": {
            **asdict(summary),
            "solver_status_counts": dict(sorted(statuses.items())),
            "min_realized_squad_points": min(scores) if scores else None,
            "p25_realized_squad_points": _percentile(scores, 0.25),
            "median_realized_squad_points": statistics.median(scores) if scores else None,
            "p75_realized_squad_points": _percentile(scores, 0.75),
            "max_realized_squad_points": max(scores) if scores else None,
        },
        "folds": folds,
        "limitations": [
            "Opening gameweeks are evaluated separately and are not included in these aggregates.",
            "The baseline is leakage-safe and explainable, not a predictive-accuracy claim.",
            "Automatic substitutions, vice-captain fallback, and bench points are excluded.",
        ],
    }


def _markdown(report: dict[str, object]) -> str:
    provenance = report["provenance"]
    configuration = report["configuration"]
    environment = report["environment"]
    summary = report["summary"]
    folds = report["folds"]
    assert isinstance(provenance, dict)
    assert isinstance(configuration, dict)
    assert isinstance(environment, dict)
    assert isinstance(summary, dict)
    assert isinstance(folds, list)

    lines = [
        "# Real-data baseline benchmark",
        "",
        f"Generated at `{report['created_utc']}` by `python -m scripts.run_baseline_benchmark`.",
        "GW1 is intentionally evaluated by the separate opening-projection workflow.",
        "",
        "## Provenance",
        "",
        f"- Repository commit: `{provenance['repository_commit']}`",
        f"- Working tree dirty: `{str(provenance['working_tree_dirty']).lower()}`",
        f"- Archive: `{provenance['archive_repository']}@{provenance['archive_commit']}`",
        f"- Manifest SHA-256: `{provenance['archive_manifest_sha256']}`",
        f"- Historical panel: `{provenance['history_rows']}` rows",
        f"- Benchmark contract: `{provenance['benchmark_contract_version']}`",
        f"- Feature contract: `{provenance['feature_generation_contract_version']}`",
        "",
        "## Configuration",
        "",
        f"- Evaluation seasons: `{', '.join(configuration['evaluation_seasons'])}`",
        f"- `form_window`: `{configuration['form_window']}` completed matches",
        f"- `min_prior_gameweeks_in_season`: `{configuration['min_prior_gameweeks_in_season']}`",
        f"- Cross-season decay: `{configuration['cross_season_decay']}`",
        f"- Cross-season minimum minutes: `{configuration['cross_season_min_minutes']}`",
        "",
        "## Aggregate results",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ]
    metrics = (
        ("Attempted folds", summary["attempted_folds"]),
        ("Feasible folds", summary["feasible_folds"]),
        ("Feasibility rate", summary["feasibility_rate"]),
        ("Mean realized squad points", summary["mean_realized_squad_points"]),
        ("Realized points stddev", summary["realized_squad_points_stddev"]),
        ("Minimum realized points", summary["min_realized_squad_points"]),
        ("25th percentile realized points", summary["p25_realized_squad_points"]),
        ("Median realized points", summary["median_realized_squad_points"]),
        ("75th percentile realized points", summary["p75_realized_squad_points"]),
        ("Maximum realized points", summary["max_realized_squad_points"]),
        ("Mean projected objective", summary["mean_projected_objective_value"]),
        ("Median solver runtime (s)", summary["median_solver_runtime_seconds"]),
        ("P95 solver runtime (s)", summary["p95_solver_runtime_seconds"]),
        ("Mean squad turnover", summary["mean_squad_turnover"]),
    )
    for name, value in metrics:
        rendered = _round_optional(value) if isinstance(value, float) else value
        lines.append(f"| {name} | {rendered} |")

    lines.extend(
        [
            "",
            "## Fold results",
            "",
            "| Fold | Status | Realized | Projected objective | Runtime (s) | Turnover |",
            "| --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for fold in folds:
        assert isinstance(fold, dict)
        lines.append(
            "| {fold_id} | {solver_status} | {realized} | {projected} | {runtime} | "
            "{turnover} |".format(
                fold_id=fold["fold_id"],
                solver_status=fold["solver_status"],
                realized=_round_optional(fold["realized_squad_points"]),
                projected=_round_optional(fold["projected_objective_value"]),
                runtime=_round_optional(fold["solver_runtime_seconds"]),
                turnover=fold["squad_turnover"],
            )
        )

    lines.extend(
        [
            "",
            "## Environment",
            "",
            f"- Platform: `{environment['platform']}`",
            f"- Processor: `{environment['processor']}`",
            f"- Logical CPUs: `{environment['logical_cpu_count']}`",
            f"- Python: `{environment['python']}`",
            f"- pandas: `{environment['pandas']}`",
            f"- OR-Tools: `{environment['ortools']}`",
            "",
            "## Limitations",
            "",
        ]
    )
    lines.extend(f"- {limitation}" for limitation in report["limitations"])
    return "\n".join(lines) + "\n"


def _write(path: Path | None, content: str) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main() -> int:
    """Load the pinned panel, run the benchmark, and emit reproducible artifacts."""

    arguments = _parse_arguments()
    archive_root: Path = arguments.archive_root
    if not archive_root.is_dir():
        print(
            f"Archive not found at {archive_root}.\n"
            "Run 'python -m scripts.fetch_historical_data' first."
        )
        return 1

    seasons = tuple(arguments.seasons or DEFAULT_BENCHMARK_SEASONS)
    panel = build_panel(archive_root)
    created_utc = datetime.now(UTC).isoformat(timespec="seconds")
    result = run_baseline_benchmark(
        panel,
        BaselineBenchmarkConfig(
            seasons=seasons,
            form_window=arguments.form_window,
            run_metadata={
                "dataset_repository": ARCHIVE_REPOSITORY,
                "dataset_commit": ARCHIVE_COMMIT,
                "created_utc": created_utc,
            },
        ),
    )
    report = _build_report(result, panel_rows=len(panel), created_utc=created_utc)
    json_text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    markdown_text = _markdown(report)

    _write(arguments.json_output, json_text)
    _write(arguments.markdown_output, markdown_text)
    if arguments.markdown_output is None:
        print(markdown_text)
    else:
        summary = report["summary"]
        assert isinstance(summary, dict)
        print(f"Wrote Markdown report to {arguments.markdown_output}")
        if arguments.json_output is not None:
            print(f"Wrote JSON report to {arguments.json_output}")
        mean_score = summary["mean_realized_squad_points"]
        rendered_mean = "n/a" if mean_score is None else f"{float(mean_score):.3f}"
        print(
            f"Folds: {summary['attempted_folds']}; "
            f"feasibility: {float(summary['feasibility_rate']):.3f}; "
            f"mean realized points: {rendered_mean}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Fit and evaluate the leakage-safe opening-gameweek price prior.

Run after ``python -m scripts.fetch_historical_data``. By default, generated
reports stay under the ignored ``artifacts/opening_prior/`` directory.
"""

import argparse
import json
import math
import sys
from dataclasses import asdict
from pathlib import Path

from squadopt.backtest import run_opening_prior_backtest
from squadopt.data.sources.vaastav import ARCHIVE_COMMIT, ARCHIVE_REPOSITORY, build_panel
from squadopt.prediction import FITTED_OPENING_PRICE_COEFFICIENT

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARCHIVE_ROOT = REPOSITORY_ROOT / "data" / "raw" / "vaastav-fpl"
DEFAULT_OUTPUT_ROOT = REPOSITORY_ROOT / "artifacts" / "opening_prior"


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument(
        "--json-output",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT / "opening_prior_backtest.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT / "opening_prior_backtest.md",
    )
    return parser.parse_args()


def _markdown(report: dict[str, object]) -> str:
    result = report["result"]
    assert isinstance(result, dict)
    rows = [
        ("Price only", result["price_only"]),
        ("Carry-over + constant", result["carry_over_with_constant"]),
        ("Carry-over + price", result["carry_over_with_price"]),
    ]
    lines = [
        "# Opening-gameweek prior backtest",
        "",
        f"- Contract: `{result['contract_version']}`",
        f"- Training seasons: `{', '.join(result['training_seasons'])}`",
        f"- Holdout season: `{result['holdout_season']}`",
        f"- Fitted coefficient: `{float(result['fitted_coefficient']):.15f}`",
        f"- Training observations: `{result['training_observations']}`",
        f"- Holdout observations: `{result['holdout_observations']}`",
        f"- Carry-over coverage: `{float(result['carry_over_coverage']):.3%}`",
        "",
        "| Rule | MAE | RMSE | Mean error |",
        "| --- | ---: | ---: | ---: |",
    ]
    for name, metrics in rows:
        assert isinstance(metrics, dict)
        lines.append(
            f"| {name} | {float(metrics['mean_absolute_error']):.6f} | "
            f"{float(metrics['root_mean_squared_error']):.6f} | "
            f"{float(metrics['mean_error']):.6f} |"
        )
    lines.extend(
        [
            "",
            "The default pipeline keeps carry-over where it exists and uses the fitted price "
            "prior only for players without a usable earlier-season record.",
            "The archive's historical GW1 price timestamp is not formally documented; the "
            "adapter uses its conservative existing GW1 treatment, while a live upcoming "
            "roster uses the unambiguous pre-season `now_cost`.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    """Run the pinned real-data fit, verify the checked-in coefficient, and report."""

    arguments = _parse_arguments()
    if not arguments.archive_root.is_dir():
        print(
            f"Archive not found at {arguments.archive_root}.\n"
            "Run 'python -m scripts.fetch_historical_data' first."
        )
        return 1

    result = run_opening_prior_backtest(build_panel(arguments.archive_root))
    if not math.isclose(
        result.fitted_coefficient,
        FITTED_OPENING_PRICE_COEFFICIENT,
        rel_tol=0.0,
        abs_tol=1e-15,
    ):
        print(
            "Fitted coefficient does not match BaselineProjectionConfig; "
            "the pinned data or fitting contract has drifted."
        )
        return 1

    report: dict[str, object] = {
        "provenance": {
            "archive_repository": ARCHIVE_REPOSITORY,
            "archive_commit": ARCHIVE_COMMIT,
        },
        "result": asdict(result),
    }
    arguments.json_output.parent.mkdir(parents=True, exist_ok=True)
    arguments.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    arguments.json_output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    arguments.markdown_output.write_text(_markdown(report), encoding="utf-8")
    print(_markdown(report), end="")
    print(f"JSON: {arguments.json_output}")
    print(f"Markdown: {arguments.markdown_output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

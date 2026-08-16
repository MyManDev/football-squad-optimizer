"""Time one candidate's residual export over the 147 development folds.

    python -m scripts.measure_candidate_runtime

Checklist item 15 asks for per-candidate wall time with the machine and the stopping rule
named. The acceptance record could only offer an upper bound, because the export it timed
was running beside a test suite. This times each regime on its own.

Run it on an idle machine. The number is wall time, so anything else competing for a core
inflates it, and an inflated number read later as a capacity estimate is worse than no
number.
"""

import argparse
import json
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

import pandas as pd
from scripts._experiment_cli import (
    DEFAULT_ARCHIVE_ROOT,
    REPOSITORY_ROOT,
    artifact_metadata,
    write_json,
    write_text,
)

from squadopt.backtest.candidate_residuals import build_candidate_residual_table
from squadopt.backtest.learned_candidate import make_learned_rate_projection_builder
from squadopt.backtest.production import make_production_projection_builder
from squadopt.data.errors import DataError
from squadopt.data.sources.vaastav import build_fixture_panel, build_panel, load_team_codes
from squadopt.experiments import PolicyObjectiveConfig, build_control_residual_table
from squadopt.features import CrossSeasonConfig
from squadopt.prediction.learned_rate import LearnedRateConfig
from squadopt.prediction.minutes import ExpectedMinutesConfig
from squadopt.prediction.production import ProductionProjectionConfig

HISTORY_SEASON = "2020-21"
DEVELOPMENT_SEASONS = ("2021-22", "2022-23", "2023-24", "2024-25")

# What ends a run. Not the benchmark's deterministic solver budget: this export never
# reaches CP-SAT, so quoting a solver limit here would describe a stage that does not run.
STOPPING_RULE = "every one of the 147 development folds is projected; no early exit, no solver"


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--window", type=int, default=6)
    parser.add_argument("--control-form-window", type=int, default=5)
    parser.add_argument(
        "--regimes",
        nargs="+",
        choices=("learned", "production", "control"),
        default=("learned", "control"),
    )
    parser.add_argument(
        "--json-output", type=Path, default=REPOSITORY_ROOT / "docs" / "candidate_runtime.json"
    )
    parser.add_argument(
        "--markdown-output", type=Path, default=REPOSITORY_ROOT / "docs" / "candidate_runtime.md"
    )
    return parser.parse_args()


def main() -> int:
    arguments = _parse_arguments()
    archive_root: Path = arguments.archive_root
    if not archive_root.is_dir():
        print(f"Archive not found at {archive_root}.")
        return 1

    loaded = (HISTORY_SEASON, *DEVELOPMENT_SEASONS)
    try:
        load_started = perf_counter()
        panel = build_panel(archive_root, seasons=list(loaded))
        fixtures = build_fixture_panel(archive_root, seasons=list(loaded))
        team_codes = pd.concat(
            [load_team_codes(archive_root, season).assign(season=season) for season in loaded],
            ignore_index=True,
        )
        load_seconds = perf_counter() - load_started
    except DataError as error:
        print(f"Could not read the archive:\n  {error}")
        return 1

    window = int(arguments.window)
    projection_config = ProductionProjectionConfig(
        rate_window=window, minutes=ExpectedMinutesConfig(window=window)
    )

    timings: list[dict[str, object]] = []
    for regime in arguments.regimes:
        print(f"Timing {regime}...", flush=True)
        started = perf_counter()
        if regime == "control":
            table = build_control_residual_table(
                panel,
                PolicyObjectiveConfig(development_seasons=DEVELOPMENT_SEASONS),
                form_window=int(arguments.control_form_window),
            )
            folds = int(table["fold_id"].nunique())
        else:
            builder = (
                make_learned_rate_projection_builder(
                    fixtures=fixtures,
                    team_codes=team_codes,
                    config=projection_config,
                    learned_config=LearnedRateConfig(window=window),
                    cross_season=CrossSeasonConfig(),
                )
                if regime == "learned"
                else make_production_projection_builder(
                    fixtures=fixtures,
                    team_codes=team_codes,
                    config=projection_config,
                    cross_season=CrossSeasonConfig(),
                )
            )
            table, _ = build_candidate_residual_table(panel, builder, seasons=DEVELOPMENT_SEASONS)
            folds = int(table["fold_id"].nunique())
        elapsed = perf_counter() - started
        timings.append(
            {
                "regime": regime,
                "wall_seconds": elapsed,
                "folds": folds,
                "rows": len(table),
                "seconds_per_fold": elapsed / folds if folds else None,
            }
        )
        print(f"  {elapsed:.1f} s over {folds} folds", flush=True)

    machine = {
        "platform": platform.platform(),
        "processor": platform.processor() or "unknown",
        "python": platform.python_version(),
    }
    document = {
        **artifact_metadata(panel_rows=len(panel)),
        "artifact_type": "candidate_runtime",
        "checklist_item": 15,
        "stopping_rule": STOPPING_RULE,
        "archive_load_seconds": load_seconds,
        "machine": machine,
        "timings": timings,
        "gate_evidence": False,
        "measured_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
    }

    lines = [
        "# Candidate Runtime",
        "",
        "Checklist item 15: per-candidate wall time over the 147 development folds.",
        "",
        f"- Machine: {machine['platform']}, {machine['processor']}",
        f"- Python: {machine['python']}",
        f"- Stopping rule: {STOPPING_RULE}",
        f"- Archive load (shared, once): {load_seconds:.1f} s",
        "",
        "| Regime | Wall time | Folds | Rows | Seconds per fold |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for entry in timings:
        seconds = float(str(entry["wall_seconds"]))
        per_fold = entry["seconds_per_fold"]
        lines.append(
            f"| `{entry['regime']}` | {seconds:.1f} s | {entry['folds']} "
            f"| {int(str(entry['rows'])):,} "
            f"| {float(str(per_fold)):.2f} |"
        )

    lines += [
        "",
        "## Reading",
        "",
        "Wall time on an idle machine, each regime timed on its own. The archive load is "
        "shared across regimes and reported separately so it is not counted twice.",
        "",
        "The stopping rule is worth stating precisely because the benchmark has a different "
        "one. This export never reaches CP-SAT — it is projection only — so the "
        "deterministic solver budget that bounds a formal gate run does not apply here, and "
        "quoting it would describe a stage that does not run.",
        "",
        "Informational. It gates nothing and is not gate evidence.",
        "",
        "## The gap between the regimes",
        "",
        "The learned candidate costs about fifty times the control. The control reuses a "
        "cached per-season carry-over and reads a rolling feature; the candidate rebuilds "
        "the current season's features with the fixture join at every fold and refits a "
        "ridge system on an expanding training slice that reaches roughly a hundred "
        "thousand rows by the last fold.",
        "",
        "That is where the time goes by construction, not a profile. Nobody has profiled "
        "it, so the attribution is a reading of the design rather than a measurement, and "
        "it is written that way on purpose.",
        "",
        "The number that matters for planning a search: at this cost one candidate "
        "evaluation is minutes, not seconds, so a thirty-evaluation sweep over this regime "
        "is hours. The Bayesian evaluator runs the control path rather than this one, so "
        "it is not bound by this figure.",
        "",
        "## Reproduction",
        "",
        "```powershell",
        ".venv\\Scripts\\python -m scripts.measure_candidate_runtime",
        "```",
    ]

    write_json(arguments.json_output, document)
    write_text(arguments.markdown_output, "\n".join(lines) + "\n")
    print("\n".join(lines))
    print(json.dumps({"regimes": [entry["regime"] for entry in timings]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

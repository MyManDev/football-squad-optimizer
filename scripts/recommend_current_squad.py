"""Recommend a squad for the next deadline that has not closed.

    python -m scripts.recommend_current_squad
    python -m scripts.recommend_current_squad --snapshot-id <id>
    python -m scripts.recommend_current_squad --snapshot-id <id> --gameweek 1

Two modes. **Live** takes the most recent capture, resolves the earliest deadline that had
not closed when it was taken, and recommends for that. **Replay** names a capture and a
gameweek and rebuilds exactly what that capture supported — which works because the capture
is immutable and checksummed, and because every other input is pinned.

Capture separately, close to the deadline:

    python -m scripts.capture_deadline_snapshot

Prices move daily and availability hourly near a deadline, so a recommendation is only as
current as the capture it came from. The report prints the capture's timestamp for exactly
that reason.

The squad is projected by the operational control, the deterministic baseline. The two-stage
production candidate was measured against the pre-registered gates and did not clear them, so
it does not decide a real squad.

Optional lower-tail diagnostics require an explicitly identified out-of-sample residual
file from that same operational control. Midseason residuals are not reused for GW1.
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

from squadopt.data.errors import DataError
from squadopt.data.snapshots import list_snapshot_ids, read_snapshot
from squadopt.data.sources.vaastav import build_panel
from squadopt.live import (
    LiveResidualHistory,
    build_recommendation,
    infer_season,
    project,
    read_inputs,
    render,
)
from squadopt.scenarios import ScenarioConfig, ScenarioError, ScenarioEvaluationConfig

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_ROOT = REPOSITORY_ROOT / "data" / "snapshots"
ARCHIVE_ROOT = REPOSITORY_ROOT / "data" / "raw" / "vaastav-fpl"


def _read_residuals(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise DataError(f"Risk residual file does not exist: {path}.")
    try:
        if path.suffix.lower() == ".csv":
            return pd.read_csv(path)
        if path.suffix.lower() in {".parquet", ".pq"}:
            return pd.read_parquet(path)
    except (OSError, ValueError, ImportError) as error:
        raise DataError(f"Could not read risk residual file {path}: {error}") from error
    raise DataError("Risk residual file must be CSV or Parquet.")


def resolve_snapshot_id(requested: str | None) -> str:
    """Pick the capture to read: the one named, or the most recent one held.

    Live mode takes the latest because that is the freshest picture of prices and
    availability. Replay names one explicitly, which is the difference between asking what
    to do now and asking what a past capture supported.
    """

    identifiers = list_snapshot_ids(SNAPSHOT_ROOT)
    if requested:
        if requested not in identifiers:
            raise DataError(
                f"No snapshot {requested!r} under {SNAPSHOT_ROOT}. Held: "
                f"{identifiers[-3:] if identifiers else 'none'}."
            )
        return requested
    if not identifiers:
        raise DataError(
            f"No snapshots under {SNAPSHOT_ROOT}. Capture one first with "
            "'python -m scripts.capture_deadline_snapshot'."
        )
    return identifiers[-1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--snapshot-id",
        help="replay this capture; omitted, the most recent capture is used",
    )
    parser.add_argument(
        "--gameweek",
        type=int,
        help="target this gameweek; omitted, the earliest deadline still open at capture time",
    )
    parser.add_argument(
        "--season",
        help="override the season; omitted, it is derived from the capture's own deadlines",
    )
    parser.add_argument("--archive-root", default=str(ARCHIVE_ROOT))
    parser.add_argument("--risk-residuals", help="CSV/Parquet OOS residual history")
    parser.add_argument("--risk-model-name")
    parser.add_argument("--risk-model-version")
    parser.add_argument("--risk-feature-contract-version")
    parser.add_argument("--risk-post-processing-contract-version")
    parser.add_argument("--risk-source-id")
    parser.add_argument("--risk-scenario-count", type=int, default=1_000)
    parser.add_argument("--risk-seed", type=int, default=0)
    parser.add_argument("--risk-min-history-folds", type=int, default=8)
    parser.add_argument("--risk-lower-quantile", type=float, default=0.10)
    parser.add_argument("--risk-worst-fraction", type=float, default=0.10)
    parser.add_argument("--risk-points-threshold", type=float, default=40.0)
    parser.add_argument("--output", help="write the report here as well as printing it")
    arguments = parser.parse_args()

    try:
        snapshot_id = resolve_snapshot_id(arguments.snapshot_id)
        snapshot = read_snapshot(SNAPSHOT_ROOT, snapshot_id)
        season = arguments.season or infer_season(snapshot)
        inputs = read_inputs(snapshot, season=season, gameweek=arguments.gameweek)

        mode = "replay" if arguments.snapshot_id else "live"
        print(
            f"{mode}: snapshot {snapshot_id}, captured {inputs.captured_at_utc}, "
            f"targeting {season} gameweek {inputs.deadline.gameweek}"
        )

        panel = build_panel(arguments.archive_root)
        projection = project(inputs, panel)
        risk_history = None
        risk_scenario_config = None
        risk_evaluation_config = None
        if arguments.risk_residuals:
            metadata = {
                "--risk-model-name": arguments.risk_model_name,
                "--risk-model-version": arguments.risk_model_version,
                "--risk-feature-contract-version": (arguments.risk_feature_contract_version),
                "--risk-post-processing-contract-version": (
                    arguments.risk_post_processing_contract_version
                ),
                "--risk-source-id": arguments.risk_source_id,
            }
            missing = [name for name, value in metadata.items() if not value]
            if missing:
                raise DataError(
                    "Risk residuals require explicit provenance arguments: "
                    + ", ".join(missing)
                    + "."
                )
            risk_history = LiveResidualHistory(
                _read_residuals(Path(arguments.risk_residuals)),
                model_name=arguments.risk_model_name,
                model_version=arguments.risk_model_version,
                feature_contract_version=arguments.risk_feature_contract_version,
                post_processing_contract_version=(arguments.risk_post_processing_contract_version),
                source_id=arguments.risk_source_id,
            )
            risk_scenario_config = ScenarioConfig(
                scenario_count=arguments.risk_scenario_count,
                deterministic_seed=arguments.risk_seed,
                min_history_folds=arguments.risk_min_history_folds,
            )
            risk_evaluation_config = ScenarioEvaluationConfig(
                lower_quantile=arguments.risk_lower_quantile,
                worst_fraction=arguments.risk_worst_fraction,
                points_threshold=arguments.risk_points_threshold,
            )
        recommendation = build_recommendation(
            inputs,
            projection,
            risk_history=risk_history,
            risk_scenario_config=risk_scenario_config,
            risk_evaluation_config=risk_evaluation_config,
        )
    except (DataError, ScenarioError) as error:
        print(f"\nCould not produce a recommendation:\n  {error}")
        return 1

    report = render(recommendation)
    print(report)

    if arguments.output:
        destination = Path(arguments.output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(report, encoding="utf-8")
        print(f"Wrote {destination}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

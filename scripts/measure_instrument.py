"""Measure #525 from named local inputs without changing decisions or live state.

See docs/measurement_instrument.md for the frozen population, centering caveat and replay.
"""

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

from squadopt.application.scoreboard import ScoreboardPublicationRequest, publish_scoreboard
from squadopt.backtest import build_walk_forward_folds, make_ridge_projection_builder
from squadopt.data.snapshots import list_snapshot_ids, read_snapshot
from squadopt.data.sources.vaastav import build_panel
from squadopt.evaluation import read_phase_c_component_handoff
from squadopt.experiments.availability_calibration import (
    availability_observations,
    calibration_report,
)
from squadopt.experiments.fold_precision import compare_precision
from squadopt.experiments.instrument_replay import projection_covariates
from squadopt.experiments.shadow_report import write_document_once
from squadopt.features import CrossSeasonConfig
from squadopt.live import season_from_bootstrap

CHECKOUT = Path(__file__).resolve().parents[1]

HISTORY = ("2020-21", "2021-22", "2022-23", "2023-24", "2024-25")
COVARIATES = (
    "component_projected_pool_mean",
    "control_projected_pool_total",
    "component_projected_pool_total",
)


def fingerprints(paths: list[Path], root: Path) -> dict[str, str]:
    result = {}
    for path in sorted(set(paths)):
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(1 << 20):
                digest.update(chunk)
        result[path.relative_to(root).as_posix()] = digest.hexdigest()
    return result


def ledger_files(root: Path) -> list[Path]:
    return sorted(path for path in (root / "data/ledger/2026-27").rglob("*") if path.is_file())


def measure(root: Path, handoff_dir: Path, preview: Path) -> dict[str, Any]:
    """One local archive scan, fixed development population and recorded score alignment."""
    revision = source_revision()
    root = root.resolve()
    handoff_dir = handoff_dir.resolve()
    snapshots_root = root / "data/snapshots"
    ids = list_snapshot_ids(snapshots_root)
    source = root / "docs/phase_c_component_evaluation.json"
    stem = handoff_dir / "phase_c_component_oof_v1"
    table, roster, manifest = (
        Path(f"{stem}{suffix}") for suffix in (".csv", ".roster.csv", ".manifest.json")
    )
    archive = root / "data/raw/vaastav-fpl"
    input_paths = [source, table, roster, manifest, root / "data/entries/registry.json"]
    input_paths += [
        archive / "data" / season / name
        for season in HISTORY
        for name in ("gws/merged_gw.csv", "players_raw.csv", "fixtures.csv", "teams.csv")
    ]
    input_paths += [
        path for name in ids for path in (snapshots_root / name).rglob("*") if path.is_file()
    ]
    ledger_inventory = ledger_files(root)
    input_paths += ledger_inventory
    before = fingerprints(input_paths, root)
    handoff = read_phase_c_component_handoff(table, roster, manifest)
    recorded = json.loads(source.read_text(encoding="utf-8"))["decision_comparison"]
    panel = build_panel(archive, seasons=HISTORY)
    print("Preparing the fixed development projections.", flush=True)
    controls = build_walk_forward_folds(
        panel,
        seasons=HISTORY[1:],
        projection_builder=make_ridge_projection_builder(cross_season=CrossSeasonConfig()),
    )
    print("Aligning the recorded decision pair with projection covariates.", flush=True)
    folds = projection_covariates(handoff, controls, recorded)
    precision = compare_precision(
        [row["difference"] for row in folds],
        {key: [row[key] for row in folds] for key in COVARIATES},
    )
    print("Joining captured availability to checked outcomes.", flush=True)
    observations, exclusions = availability_observations(
        (read_snapshot(snapshots_root, name) for name in ids), season_of=season_from_bootstrap
    )
    calibration = calibration_report(observations, exclusions)
    live_ids = list_snapshot_ids(snapshots_root, source="fpl-live")
    if not live_ids:
        raise ValueError("A live capture is required for the scoreboard measurement.")
    scoreboard = publish_scoreboard(
        ScoreboardPublicationRequest(
            snapshots_root,
            live_ids[-1],
            root / "data/entries/registry.json",
            root / "data/ledger",
            preview,
            352490,
            season="2026-27",
        )
    )
    weeks = scoreboard.document["payload"]["gameweeks"]
    error_rows = [
        {
            "gameweek": week["gameweek"],
            "finished": week["finished"],
            "data_checked": week["data_checked"],
            "system": week["comparisons"][0],
        }
        for week in weeks
    ]
    if (
        before != fingerprints(input_paths, root)
        or ids != list_snapshot_ids(snapshots_root)
        or ledger_inventory != ledger_files(root)
    ):
        raise ValueError("Measurement inputs changed during the run; no record was written.")
    if source_revision() != revision:
        raise ValueError("Measurement source revision changed during the run.")
    return {
        "contract_version": "measurement_instrument_v1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "repository_commit": revision,
        "input_sha256": before,
        "environment": {
            name: version(name) for name in ("numpy", "pandas", "scipy", "scikit-learn", "ortools")
        },
        "comparison": (
            "Phase C component base minus historical ridge control; official_autosub_captain_v2"
        ),
        "population": [row["fold_id"] for row in folds],
        "folds": folds,
        "locked_holdout_used_as_input": False,
        "covariate_timing": (
            "OOF manifest's structural pre-decision contract; archive deadline "
            "timestamps absent, never inferred from kickoff"
        ),
        "precision": precision,
        "rejected_covariates": {
            "same_week_template_realized_score": (
                "outcome unavailable at the deadline; historical ownership timing is "
                "also unverified"
            ),
            "same_week_game_average": "outcome unavailable at the deadline",
            "same_week_realized_total_points": "outcome unavailable at the deadline",
        },
        "error_decomposition": error_rows,
        "availability": calibration,
        "decisions_changed": False,
        "promotion_gate_changed": False,
        "method_source": (
            "https://ai.stanford.edu/~ronnyk/2013-02CUPEDImprovingSensitivityOfControlledExperiments.pdf"
        ),
    }


def source_revision() -> str:
    status = subprocess.check_output(["git", "status", "--porcelain"], cwd=CHECKOUT, text=True)
    if status.strip():
        raise ValueError("Commit measurement source changes before running.")
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=CHECKOUT, text=True).strip()


def validate_destinations(preview: Path, output: Path, checkout: Path) -> None:
    preview, output, checkout = preview.resolve(), output.resolve(), checkout.resolve()
    if not preview.is_relative_to(checkout / ".pt") or preview == checkout / ".pt":
        raise ValueError("preview-root must be a new child of this checkout's .pt directory")
    if preview.exists():
        raise ValueError(
            "preview-root already exists; old publications cannot supply measurement rows"
        )
    if not any(output.is_relative_to(checkout / name) for name in ("docs", "artifacts", ".pt")):
        raise ValueError("output must be inside this checkout's docs, artifacts or .pt directory")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--handoff-dir", type=Path, required=True)
    parser.add_argument("--preview-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    preview = args.preview_root.resolve()
    root = args.source_root.resolve()
    try:
        validate_destinations(preview, args.output, CHECKOUT)
    except ValueError as error:
        parser.error(str(error))
    document = measure(root, args.handoff_dir, preview)
    print(write_document_once(document, args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Run the pre-registered Benchmark V2 on frozen development and live inputs."""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from scripts._experiment_cli import artifact_metadata, write_json, write_text

from squadopt.data.errors import DataError
from squadopt.data.snapshots import read_snapshot
from squadopt.data.sources.vaastav import build_panel
from squadopt.evaluation import EvaluationValidationError
from squadopt.experiments.benchmark_v2 import (
    BENCHMARK_V2_CONTRACT_VERSION,
    DEVELOPMENT_SEASONS,
    measure_historical_v1_v2,
    measure_settled_entry_parity,
    validate_top100_capture,
)
from squadopt.experiments.control_residuals import build_control_residual_table
from squadopt.experiments.policy_objective import PolicyObjectiveConfig
from squadopt.experiments.residual_signal_scan import load_enrichment_rows

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
HISTORY_SEASONS = ("2020-21", *DEVELOPMENT_SEASONS)


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, required=True)
    parser.add_argument("--snapshot-root", type=Path, required=True)
    parser.add_argument("--parity-snapshot-id", required=True)
    parser.add_argument("--top100-snapshot-id", required=True)
    parser.add_argument("--top100-target-gameweek", type=int, default=3)
    parser.add_argument(
        "--json-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "benchmark_v2.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "benchmark_v2.md",
    )
    return parser.parse_args()


def _require_clean_checkout() -> str:
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if dirty:
        raise EvaluationValidationError(
            "Benchmark V2 refuses a dirty checkout; commit the preregistration and "
            "implementation before the binding run."
        )
    return revision


def _markdown(document: dict[str, object]) -> str:
    historical = document["historical"]
    parity = document["entry_parity"]
    top100 = document["top100"]
    assert isinstance(historical, dict)
    assert isinstance(parity, dict)
    assert isinstance(top100, dict)
    summary = historical["summary"]
    assert isinstance(summary, dict)
    lines = [
        "# Benchmark V2",
        "",
        f"- Contract: `{document['contract_version']}`",
        f"- Phase status: `{document['phase_status']}`",
        "- Historical ownership timing is unverified, so the historical comparison is "
        "descriptive and cannot promote a model.",
        "- The locked 2025-26 holdout was not read.",
        "",
        "## Real-entry scoring parity",
        "",
        f"- Snapshot: `{parity['snapshot_id']}`; gameweek {parity['gameweek']}",
        f"- Exact matches: **{parity['exact_matches']}/{parity['entries_compared']}**",
        f"- Maximum absolute difference: {parity['max_absolute_difference']}",
        f"- Status: `{parity['status']}`",
        "",
        "## Paired historical V1/V2 comparison",
        "",
        f"- Folds: {summary['folds']}",
        f"- Mean V1 template-minus-system gap: {summary['mean_v1_gap_template_minus_system']:+.3f}",
        f"- Mean V2 template-minus-system gap: {summary['mean_v2_gap_template_minus_system']:+.3f}",
        f"- Mean overall gap change: {summary['mean_overall_gap_change']:+.3f}",
        f"- Mean template construction effect under V1 scoring: "
        f"{summary['mean_template_construction_effect_under_v1']:+.3f}",
        f"- Mean system scoring effect: {summary['mean_system_scoring_effect']:+.3f}",
        f"- Mean constrained-template scoring effect: "
        f"{summary['mean_template_scoring_effect']:+.3f}",
        "",
        "| Season | Folds | V1 gap | V2 gap | Change |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    per_season = historical["per_season"]
    assert isinstance(per_season, dict)
    for season in DEVELOPMENT_SEASONS:
        entry = per_season[season]
        assert isinstance(entry, dict)
        lines.append(
            f"| {season} | {entry['folds']} | {entry['mean_v1_gap']:+.3f} "
            f"| {entry['mean_v2_gap']:+.3f} | {entry['mean_gap_change']:+.3f} |"
        )
    lines += [
        "",
        "## Prospective Top-100 cohort",
        "",
        f"- Snapshot: `{top100['snapshot_id']}`",
        f"- Target gameweek: {top100['target_gameweek']}; members: {top100['member_count']}",
        f"- Captured: {top100['captured_at_utc']}; deadline: {top100['deadline_timestamp_utc']}",
        f"- Status: `{top100['status']}` — no outcome exists until gameweek settlement.",
        "",
        "No Top-100 performance claim is made. The prospective cohort is frozen and will "
        "be scored after settlement without member replacement.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    arguments = _parse_arguments()
    try:
        revision = _require_clean_checkout()
        parity_snapshot = read_snapshot(arguments.snapshot_root, arguments.parity_snapshot_id)
        top100_snapshot = read_snapshot(arguments.snapshot_root, arguments.top100_snapshot_id)
        parity = measure_settled_entry_parity(
            parity_snapshot,
            season="2026-27",
            gameweek=1,
        )
        _, top100 = validate_top100_capture(
            top100_snapshot,
            target_gameweek=arguments.top100_target_gameweek,
        )
        panel = build_panel(arguments.archive_root, seasons=HISTORY_SEASONS)
        objective = PolicyObjectiveConfig(development_seasons=DEVELOPMENT_SEASONS)
        residuals = build_control_residual_table(panel, objective)
        ownership = load_enrichment_rows(arguments.archive_root, DEVELOPMENT_SEASONS)
        historical = measure_historical_v1_v2(residuals, panel, ownership)
    except (
        DataError,
        EvaluationValidationError,
        OSError,
        subprocess.CalledProcessError,
        ValueError,
    ) as error:
        print(f"Benchmark V2 refused: {error}")
        return 1

    created_utc = datetime.now(UTC).isoformat(timespec="seconds")
    document = {
        **artifact_metadata(
            panel_rows=len(panel),
            created_utc=created_utc,
            history_seasons=HISTORY_SEASONS,
        ),
        "contract_version": BENCHMARK_V2_CONTRACT_VERSION,
        "preregistration": "docs/benchmark_v2_prereg.md",
        "repository_commit": revision,
        "phase_status": "insufficient_evidence",
        "entry_parity": parity,
        "historical": historical,
        "top100": top100,
        "locked_holdout_accessed": False,
    }
    markdown = _markdown(document)
    write_json(arguments.json_output, document)
    write_text(arguments.markdown_output, markdown)
    print(markdown)
    print(f"Wrote {arguments.json_output}")
    print(f"Wrote {arguments.markdown_output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

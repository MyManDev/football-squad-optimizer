r"""Evaluate the verified Phase C component handoff without promoting it.

    python -m scripts.evaluate_phase_c_components \
        --table <phase_c_component_oof_v1.csv> \
        --manifest <phase_c_component_oof_v1.manifest.json> \
        --roster <phase_c_component_oof_v1.roster.csv> \
        --producer-environment <environment_versions.json> \
        --archive-root <pinned-vaastav-archive>

The command reads explicitly named development seasons, never the locked 2025-26
holdout. It produces descriptive component and paired decision diagnostics. No threshold
is selected here and no model is promoted by this report.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import warnings
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, cast

from scripts._experiment_cli import DEFAULT_ARCHIVE_ROOT, REPOSITORY_ROOT, artifact_metadata

from squadopt.backtest import (
    BacktestConfigurationError,
    build_walk_forward_folds,
    make_ridge_projection_builder,
)
from squadopt.data import DataError
from squadopt.data.sources.vaastav import build_panel
from squadopt.evaluation import (
    EvaluationConfig,
    EvaluationError,
    ScoringPolicy,
    evaluate_component_oof,
    evaluate_phase_c_component_decisions,
    read_phase_c_component_handoff,
)
from squadopt.experiments.phase_c_reporting import (
    phase_c_component_evaluation_to_dict,
    phase_c_decision_comparison_to_dict,
)
from squadopt.experiments.shadow_report import ShadowReportError, write_document_once
from squadopt.features import CrossSeasonConfig

REPORT_VERSION: Final = "phase_c_component_evaluation_v1"
HISTORY_SEASONS: Final = (
    "2020-21",
    "2021-22",
    "2022-23",
    "2023-24",
    "2024-25",
)
DECISION_SEASONS: Final = HISTORY_SEASONS[1:]
DEFAULT_OUTPUT: Final = REPOSITORY_ROOT / "docs" / "phase_c_component_evaluation.json"


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--roster", type=Path, required=True)
    parser.add_argument("--producer-environment", type=Path, required=True)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _producer_environment(
    path: Path, *, table_sha256: str, repository_commit: str
) -> dict[str, object]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Cannot read producer environment {path}: {error}") from error
    if not isinstance(document, dict):
        raise ValueError("Producer environment must be a JSON object.")
    if document.get("table_sha256") != table_sha256:
        raise ValueError("Producer environment names a different OOF table digest.")
    if document.get("repository_commit") != repository_commit:
        raise ValueError("Producer environment names a different repository commit.")
    required = ("python", "numpy", "pandas", "scipy", "scikit_learn")
    if any(not isinstance(document.get(field), str) or not document[field] for field in required):
        raise ValueError("Producer environment is missing a required package version.")
    return {
        "file_sha256": _sha256(path),
        **{field: document[field] for field in required},
    }


def _recorded_warnings(caught: list[warnings.WarningMessage]) -> list[str]:
    counted = Counter(f"{type(item.message).__name__}: {item.message}" for item in caught)
    return [
        text if count == 1 else f"{text} (raised {count} times)"
        for text, count in sorted(counted.items())
    ]


def _measure(arguments: argparse.Namespace) -> dict[str, object]:
    handoff = read_phase_c_component_handoff(arguments.table, arguments.roster, arguments.manifest)
    producer = _producer_environment(
        arguments.producer_environment,
        table_sha256=handoff.table_sha256,
        repository_commit=handoff.repository_commit,
    )
    panel = build_panel(arguments.archive_root, seasons=HISTORY_SEASONS)
    controls = build_walk_forward_folds(
        panel,
        seasons=DECISION_SEASONS,
        projection_builder=make_ridge_projection_builder(cross_season=CrossSeasonConfig()),
    )
    config = EvaluationConfig(
        scoring_policy=ScoringPolicy.OFFICIAL_AUTOSUB_CAPTAIN_V2,
        run_metadata={"study": REPORT_VERSION},
    )
    player_metrics = evaluate_component_oof(handoff.rows)
    decisions = evaluate_phase_c_component_decisions(handoff, controls, config)
    return {
        "source": {
            "table_sha256": handoff.table_sha256,
            "roster_sha256": handoff.roster_sha256,
            "producer_repository_commit": handoff.repository_commit,
            "producer_environment": producer,
        },
        "player_metrics": phase_c_component_evaluation_to_dict(player_metrics),
        "decision_comparison": phase_c_decision_comparison_to_dict(decisions),
        "panel_rows": len(panel),
    }


def main() -> int:
    arguments = _parse_arguments()
    started = datetime.now(UTC)
    metadata = artifact_metadata(
        panel_rows=0,
        created_utc=started.isoformat(timespec="seconds"),
        history_seasons=HISTORY_SEASONS,
    )
    provenance = metadata["provenance"]
    assert isinstance(provenance, dict)
    if provenance["working_tree_dirty"]:
        print("Refused: commit or stash working-tree changes before measuring Phase C.")
        return 1

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            measured = _measure(arguments)
        except (
            BacktestConfigurationError,
            DataError,
            EvaluationError,
            OSError,
            ValueError,
            ShadowReportError,
        ) as error:
            print(f"Refused: {error}")
            return 1
    completed = datetime.now(UTC)
    panel_rows = cast(int, measured.pop("panel_rows"))
    metadata = artifact_metadata(
        panel_rows=panel_rows,
        created_utc=started.isoformat(timespec="seconds"),
        history_seasons=HISTORY_SEASONS,
    )
    document: dict[str, object] = {
        "contract_version": REPORT_VERSION,
        "created_utc": metadata["created_utc"],
        "descriptive_only": True,
        "promotion_decision": "not_evaluated",
        "operational_control_changed": False,
        "locked_holdout_accessed": False,
        "execution": {
            "started_at_utc": started.isoformat(timespec="seconds"),
            "completed_at_utc": completed.isoformat(timespec="seconds"),
            "elapsed_seconds": (completed - started).total_seconds(),
            "warnings": _recorded_warnings(caught),
        },
        "provenance": metadata["provenance"],
        "evaluation_environment": metadata["environment"],
        **measured,
    }
    try:
        outcome = write_document_once(document, arguments.json_output)
    except ShadowReportError as error:
        print(f"Refused: {error}")
        return 1
    decision = document["decision_comparison"]
    assert isinstance(decision, dict)
    diagnostics = decision["diagnostics"]
    assert isinstance(diagnostics, dict)
    print(f"Folds      {diagnostics['comparable_folds']}/{diagnostics['attempted_folds']}")
    print(f"Mean delta {diagnostics['mean_difference']}")
    print(
        "W/T/L      "
        f"{diagnostics['candidate_wins']}/{diagnostics['ties']}/"
        f"{diagnostics['candidate_losses']}"
    )
    print(f"Wrote      {arguments.json_output} ({outcome})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

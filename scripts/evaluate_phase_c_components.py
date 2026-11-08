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
import json
import sys
import warnings
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Final, cast

import pandas as pd
from scripts._experiment_cli import (
    DEFAULT_ARCHIVE_ROOT,
    REPOSITORY_ROOT,
    _sha256,
    artifact_metadata,
    measurement_optimization_config,
    solver_record,
)

from squadopt.backtest import (
    BacktestConfigurationError,
    build_walk_forward_folds,
    make_ridge_projection_builder,
)
from squadopt.data import DataError
from squadopt.data.sources.vaastav import (
    GAMEWEEK_FILE,
    ROSTER_FILE,
    attach_player_code,
    build_panel,
    drop_non_player_rows,
    season_directory,
)
from squadopt.evaluation import (
    EvaluationConfig,
    EvaluationError,
    EvaluationFold,
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
from squadopt.optimization import OptimizationConfig

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
    # Development-only: read a Phase C v2 development artifact (the declared estimator or
    # weighting candidates) through the development reader and score its decisions on the
    # same development seasons. The output then names the contract it was read under and
    # is not the frozen v1 evaluation; a default output path is refused for it.
    parser.add_argument("--development-contract", default=None)
    # Measurement options (docs/research/phase_c_solver_budget_cards_method.md). The defaults
    # are the measurement configuration every committed record ran under; a different
    # deterministic budget, the official card-participation rule or the recorded squads make
    # the output a development reading that must name its own --json-output.
    parser.add_argument("--solver-deterministic-budget", type=float, default=None)
    parser.add_argument("--solver-wall-cap-seconds", type=float, default=None)
    parser.add_argument("--card-participation", action="store_true")
    parser.add_argument("--record-decisions", action="store_true")
    return parser.parse_args()


def load_card_participation(archive_root: Path, seasons: Sequence[str]) -> pd.DataFrame:
    """Which players were booked in each gameweek, read from the archive's gameweek files.

    The canonical panel carries no card columns, so this reads `merged_gw.csv` directly:
    non-player rows are dropped and the per-season `element` is mapped to the persistent
    player code as the adapter does, then a player-gameweek is booked when any of its
    fixture rows carries a yellow or red card. Nothing else is read from the files.
    """

    frames = []
    for season in seasons:
        directory = season_directory(archive_root, season)
        gameweeks = pd.read_csv(
            directory / GAMEWEEK_FILE,
            usecols=["element", "round", "position", "yellow_cards", "red_cards"],
            dtype=str,
            encoding="utf-8",
            encoding_errors="replace",
        )
        roster = pd.read_csv(directory / ROSTER_FILE, usecols=["id", "code"], dtype=str)
        players = attach_player_code(drop_non_player_rows(gameweeks), roster)
        booked = pd.to_numeric(players["yellow_cards"], errors="coerce").fillna(0).gt(0) | (
            pd.to_numeric(players["red_cards"], errors="coerce").fillna(0).gt(0)
        )
        frame = cast(
            pd.DataFrame,
            players.assign(card_participation=booked)
            .groupby(["player_code", "round"], as_index=False)["card_participation"]
            .any(),
        )
        frames.append(
            pd.DataFrame(
                {
                    "season": season,
                    "gameweek": pd.to_numeric(frame["round"], errors="raise").astype("int64"),
                    "player_id": pd.to_numeric(frame["player_code"], errors="raise").astype(
                        "int64"
                    ),
                    "card_participation": frame["card_participation"].astype(bool),
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def _with_card_participation(
    folds: tuple[EvaluationFold, ...], cards: pd.DataFrame
) -> tuple[EvaluationFold, ...]:
    """Each control fold's outcomes with the archive's card participation beside them.

    A player with a yellow or red card in the gameweek participated under the official
    automatic-substitution rule even without a minute.
    """

    rebuilt = []
    for fold in folds:
        season, gameweek = fold.fold_id[:7], int(fold.fold_id.rsplit("gw", 1)[1])
        booked = cards.loc[
            cards["season"].eq(season) & cards["gameweek"].eq(gameweek),
            ["player_id", "card_participation"],
        ]
        realized = fold.realized_points.merge(
            booked, on="player_id", how="left", validate="one_to_one"
        )
        realized["card_participation"] = realized["card_participation"].fillna(False).astype(bool)
        rebuilt.append(
            EvaluationFold(
                fold_id=fold.fold_id,
                projections=fold.projections,
                realized_points=realized,
                metadata=fold.metadata,
            )
        )
    return tuple(rebuilt)


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


def _load_development_panel(archive_root: Path) -> pd.DataFrame:
    panel = build_panel(archive_root, seasons=HISTORY_SEASONS)
    observed = {str(value) for value in panel["season"].dropna().unique()}
    expected = set(HISTORY_SEASONS)
    if observed != expected:
        raise DataError(
            "Phase C panel seasons differ from the explicit development history: "
            f"expected {sorted(expected)!r}, observed {sorted(observed)!r}."
        )
    return panel


def _measure(arguments: argparse.Namespace) -> dict[str, object]:
    development_contract = (
        None if arguments.development_contract is None else str(arguments.development_contract)
    )
    handoff = read_phase_c_component_handoff(
        arguments.table,
        arguments.roster,
        arguments.manifest,
        development_contract=development_contract,
    )
    producer = _producer_environment(
        arguments.producer_environment,
        table_sha256=handoff.table_sha256,
        repository_commit=handoff.repository_commit,
    )
    panel = _load_development_panel(arguments.archive_root)
    controls = build_walk_forward_folds(
        panel,
        seasons=DECISION_SEASONS,
        projection_builder=make_ridge_projection_builder(cross_season=CrossSeasonConfig()),
    )
    optimization_config = measurement_optimization_config()
    if arguments.solver_deterministic_budget is not None or arguments.solver_wall_cap_seconds:
        optimization_config = OptimizationConfig(
            solver_time_limit_seconds=(
                arguments.solver_wall_cap_seconds
                if arguments.solver_wall_cap_seconds is not None
                else optimization_config.solver_time_limit_seconds
            ),
            solver_deterministic_time_limit=(
                arguments.solver_deterministic_budget
                if arguments.solver_deterministic_budget is not None
                else optimization_config.solver_deterministic_time_limit
            ),
        )
    if arguments.card_participation:
        controls = _with_card_participation(
            controls, load_card_participation(arguments.archive_root, DECISION_SEASONS)
        )
    config = EvaluationConfig(
        # Both arms solve under the measurement budget rather than the dataclass default,
        # so which arm wins cannot depend on how busy the machine was (#590).
        optimization_config=optimization_config,
        scoring_policy=ScoringPolicy.OFFICIAL_AUTOSUB_CAPTAIN_V2,
        run_metadata={"study": REPORT_VERSION},
    )
    player_metrics = evaluate_component_oof(handoff.rows)
    decisions = evaluate_phase_c_component_decisions(
        handoff,
        controls,
        config,
        development_contract=development_contract,
        record_decisions=arguments.record_decisions,
    )
    measurement_options = {
        "solver_deterministic_budget": optimization_config.solver_deterministic_time_limit,
        "solver_wall_cap_seconds": optimization_config.solver_time_limit_seconds,
        "card_participation": bool(arguments.card_participation),
        "record_decisions": bool(arguments.record_decisions),
        "is_measurement_configuration": optimization_config == measurement_optimization_config()
        and not arguments.card_participation,
    }
    return {
        "development_contract": development_contract,
        "development_only": development_contract is not None,
        "measurement_options": measurement_options,
        "source": {
            "table_sha256": handoff.table_sha256,
            "roster_sha256": handoff.roster_sha256,
            "manifest_sha256": handoff.manifest_sha256,
            "producer_repository_commit": handoff.repository_commit,
            "model_version": handoff.model_version,
            "feature_contract_version": handoff.feature_contract_version,
            "target_contract_version": handoff.target_contract_version,
            "dataset_contract_version": handoff.dataset_contract_version,
            "producer_environment": producer,
        },
        "player_metrics": phase_c_component_evaluation_to_dict(player_metrics),
        "decision_comparison": phase_c_decision_comparison_to_dict(decisions),
        # One block, because one configuration ran: the control and the component base are
        # two arms of the same comparison and share `config`, so their statuses pool.
        "solver": solver_record(decisions.control, decisions.component_base),
        "panel_rows": len(panel),
    }


def main() -> int:
    arguments = _parse_arguments()
    if arguments.development_contract is not None and arguments.json_output == DEFAULT_OUTPUT:
        print(
            "A development-contract evaluation is not the frozen Phase C record; name a "
            "separate --json-output."
        )
        return 1
    if arguments.json_output == DEFAULT_OUTPUT and (
        arguments.solver_deterministic_budget is not None
        or arguments.solver_wall_cap_seconds is not None
        or arguments.card_participation
        or arguments.record_decisions
    ):
        print(
            "A measurement under other solver limits, the card rule or recorded squads is not "
            "the frozen Phase C record; name a separate --json-output."
        )
        return 1
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
    evaluation_environment = dict(cast(Mapping[str, object], metadata["environment"]))
    evaluation_environment.update(
        {
            "numpy": version("numpy"),
            "scipy": version("scipy"),
            "scikit_learn": version("scikit-learn"),
        }
    )
    document: dict[str, object] = {
        "contract_version": REPORT_VERSION,
        "generated_at_utc": metadata["created_utc"],
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
        "evaluation_environment": evaluation_environment,
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

"""Run the pre-registered exact score-component attribution diagnostic."""

import argparse
import hashlib
import json
import math
import sys
import warnings
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, cast

import pandas as pd
from scripts._experiment_cli import (
    DEFAULT_ARCHIVE_ROOT,
    REPOSITORY_ROOT,
    _git_revision,
    artifact_metadata,
)
from scripts.run_tail_diagnostic import (
    MODEL_NAME,
    _projection_provider,
    _recorded_warnings,
    _tree_dirty_ignoring,
)

from squadopt.backtest.splits import walk_forward_decision_points
from squadopt.data.errors import DataSourceError
from squadopt.data.loaders import load_csv
from squadopt.data.sources.vaastav import (
    GAMEWEEK_FILE,
    ROSTER_FILE,
    attach_player_code,
    drop_non_player_rows,
    season_directory,
)
from squadopt.evaluation.scoring import score_realized_squad_points
from squadopt.experiments.component_attribution import (
    COMPONENTS,
    CONTRACT_VERSION,
    IDENTITY_TOLERANCE,
    MIN_PLAYER_HISTORY,
    aggregate_player_gameweeks,
    attribute_fold,
    classify,
    score_fixture_components,
    summarise,
)
from squadopt.experiments.residual_manifest import (
    ResidualSourceError,
    load_residual_source_manifest,
)
from squadopt.experiments.shadow_calibration import BOOTSTRAP_SEED, CONFIDENCE_LEVEL
from squadopt.experiments.shadow_report import ShadowReportError, write_document_once
from squadopt.experiments.shadow_squad_calibration import (
    BOOTSTRAP_RESAMPLES,
    MIN_PRIOR_GAMEWEEKS_IN_SEASON,
    SquadFold,
    SquadShadowConfig,
    SquadShadowError,
    _require,
    _scenario_config,
    build_squad_folds,
    declared_parameters,
    frozen_history_fold_ids,
    load_panel_without_the_holdout,
    loaded_seasons,
)
from squadopt.experiments.tail_diagnostic import (
    CONTROL_SCALE,
    FROZEN_SHIFT_POINTS,
    SCREENING_SEASONS,
    SENSITIVITY_SEASON,
    STUDY_SEASONS,
    VALIDATION_SEASON,
    _evaluation_config,
    control_replay,
    eligible_development_folds,
    optimize_squad_once,
    refuse_the_holdout,
)
from squadopt.prediction import PredictionProvenance, prepare_optimizer_projection
from squadopt.prediction.in_season import (
    IN_SEASON_FEATURE_CONTRACT_VERSION,
    IN_SEASON_MODEL_VERSION,
)
from squadopt.scenarios import ScenarioTarget, evaluate_fixed_decision, generate_scenarios

PRIOR_ARTIFACT: Final = REPOSITORY_ROOT / "docs" / "phase2_projection_conditional_returns.json"
POPULATION_ARTIFACT: Final = REPOSITORY_ROOT / "docs" / "phase2_marginal_downside_sources.json"
SOURCE_ARTIFACTS: Final = (
    REPOSITORY_ROOT / "docs" / "shadow_calibration_squad.json",
    POPULATION_ARTIFACT,
    PRIOR_ARTIFACT,
)
DEFAULT_OUTPUT: Final = REPOSITORY_ROOT / "docs" / "phase2_component_attribution.json"
_RAW_COLUMNS: Final = (
    "element",
    "fixture",
    "round",
    "position",
    "minutes",
    "total_points",
    "goals_scored",
    "assists",
    "clean_sheets",
    "goals_conceded",
    "saves",
    "bonus",
    "yellow_cards",
    "red_cards",
    "own_goals",
    "penalties_missed",
    "penalties_saved",
)


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--residual-table", type=Path, required=True)
    parser.add_argument("--residual-manifest", type=Path, required=True)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def _digests() -> dict[str, str]:
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in SOURCE_ARTIFACTS}


def _recorded_population() -> dict[str, object]:
    document = json.loads(POPULATION_ARTIFACT.read_text(encoding="utf-8"))
    universe = document.get("fold_universe")
    _require(isinstance(universe, Mapping), "the prior artifact has no fold universe.")
    folds = universe.get("folds_by_season")
    _require(isinstance(folds, Mapping), "the prior artifact has no seasonal fold counts.")
    normalized: dict[str, int] = {}
    for season in STUDY_SEASONS:
        value = folds.get(season)
        _require(type(value) is int, f"the prior artifact has no {season} fold count.")
        normalized[season] = int(value)
    total_folds = universe.get("total_folds")
    starter_rows = universe.get("starter_rows")
    _require(type(total_folds) is int, "the prior artifact has no total fold count.")
    _require(type(starter_rows) is int, "the prior artifact has no starter-row count.")
    return {
        "folds_by_season": normalized,
        "total_folds": int(total_folds),
        "starter_rows": int(starter_rows),
    }


def reconcile_population(
    readings: pd.DataFrame,
    diagnostics: pd.DataFrame,
    recorded: Mapping[str, object],
) -> None:
    """Require the fixed-XI fold and starter population to match the prior study."""

    folds = cast(Mapping[str, int], recorded["folds_by_season"])
    control = readings.loc[readings["arm"].astype(str).eq("control")]
    _require(
        int(control["fold_id"].nunique()) == int(cast(int, recorded["total_folds"])),
        "the component fold population does not reproduce the prior artifact.",
    )
    _require(
        int(diagnostics["starter_count"].sum()) == int(cast(int, recorded["starter_rows"])),
        "the component starter population does not reproduce the prior artifact.",
    )
    for season in STUDY_SEASONS:
        measured = int(control.loc[control["season"].astype(str).eq(season), "fold_id"].nunique())
        _require(
            measured == int(folds[season]),
            f"the {season} fold population does not reproduce the prior artifact.",
        )


def load_component_outcomes(archive_root: Path, seasons: Sequence[str]) -> pd.DataFrame:
    """Load exact fixture score components for explicit non-holdout seasons."""

    requested = tuple(str(season) for season in seasons)
    refuse_the_holdout(requested)
    _require(
        bool(requested) and len(requested) == len(set(requested)),
        "component seasons repeat or are empty.",
    )
    frames: list[pd.DataFrame] = []
    for season in requested:
        directory = season_directory(archive_root, season)
        gameweek_path = directory / GAMEWEEK_FILE
        roster_path = directory / ROSTER_FILE
        if not gameweek_path.is_file() or not roster_path.is_file():
            raise DataSourceError(f"component source files are missing for {season}.")
        gameweeks = load_csv(gameweek_path)
        roster = load_csv(roster_path)
        missing = sorted(set(_RAW_COLUMNS) - set(gameweeks.columns))
        _require(not missing, f"{season} component source is missing columns {missing!r}.")
        _require(
            {"id", "code"}.issubset(roster.columns), f"{season} roster identity is incomplete."
        )
        players = drop_non_player_rows(gameweeks)
        players = players.drop_duplicates(subset=["element", "round", "fixture"], keep="first")
        joined = attach_player_code(players, roster)
        player_ids = pd.to_numeric(joined["player_code"], errors="coerce")
        gameweeks_numeric = pd.to_numeric(joined["round"], errors="coerce")
        fixture_ids = pd.to_numeric(joined["fixture"], errors="coerce")
        _require(
            not bool(
                player_ids.isna().any()
                or gameweeks_numeric.isna().any()
                or fixture_ids.isna().any()
            ),
            f"{season} component identities must be numeric.",
        )
        prepared = joined.loc[:, list(_RAW_COLUMNS)].rename(
            columns={"player_code": "player_id", "round": "gameweek", "fixture": "fixture_id"}
        )
        # player_code is attached after the raw projection above.
        prepared["player_id"] = player_ids.astype("int64")
        prepared["gameweek"] = gameweeks_numeric.astype("int64")
        prepared["fixture_id"] = fixture_ids.astype("int64")
        prepared["season"] = season
        prepared["fold_id"] = [
            f"{season}-gw{int(gameweek):02d}" for gameweek in prepared["gameweek"]
        ]
        frames.append(aggregate_player_gameweeks(score_fixture_components(prepared)))
    result = pd.concat(frames, ignore_index=True)
    _require(
        {str(value) for value in result["season"]} == set(requested),
        "component outcomes do not cover the requested seasons.",
    )
    return result


def _read_fold(
    fold: SquadFold,
    residuals: pd.DataFrame,
    components: pd.DataFrame,
    history_fold_ids: Sequence[str],
    provenance: PredictionProvenance,
    config: SquadShadowConfig,
) -> tuple[pd.DataFrame, dict[str, object]]:
    decision = optimize_squad_once(fold, config)
    starter_ids = decision.starting_xi["player_id"].tolist()
    _require(
        len(starter_ids) == 11 and len(set(starter_ids)) == 11, "a fold needs eleven starters."
    )
    _require(decision.captain is not None, "a fold decision has no captain.")
    assert decision.captain is not None
    captain_id = decision.captain["player_id"]
    snapshot = prepare_optimizer_projection(
        fold.projections.loc[:, ["player_id", "name", "team_id", "position", "price_tenths"]],
        fold.projections.loc[:, ["player_id", "expected_points"]],
        provenance,
    )
    history = residuals.loc[residuals["fold_id"].astype(str).isin(set(history_fold_ids))]
    scenarios = generate_scenarios(
        snapshot, history, ScenarioTarget(fold.season, fold.gameweek), _scenario_config(config)
    )
    evaluated = evaluate_fixed_decision(
        decision, scenarios, _evaluation_config(config, scale=CONTROL_SCALE)
    )
    projection_rows = snapshot.table.set_index("player_id")
    _require(
        all(player_id in projection_rows.index for player_id in starter_ids),
        "a starter has no projection.",
    )
    starters = projection_rows.loc[starter_ids, ["position", "expected_points"]].reset_index()
    starters.insert(0, "fold_id", fold.fold_id)
    starters.insert(1, "season", fold.season)
    starters["weight"] = [
        2.0 if player_id == captain_id else 1.0 for player_id in starters["player_id"]
    ]
    target = components.loc[components["fold_id"].astype(str).eq(fold.fold_id)]
    readings, diagnostics = attribute_fold(
        starters,
        target,
        components,
        history_fold_ids,
        evaluated.scenario_scores,
        shift_points=FROZEN_SHIFT_POINTS,
        lower_quantile=config.lower_quantile,
    )
    canonical = score_realized_squad_points(decision, fold.realized_points)
    measured = float(readings.loc[readings["arm"].eq("control"), "realized_score"].iloc[0])
    _require(
        math.isclose(canonical, measured, rel_tol=0.0, abs_tol=IDENTITY_TOLERANCE),
        f"{fold.fold_id}: component score does not reproduce canonical realized score.",
    )
    return readings, {
        "fold_id": fold.fold_id,
        "season": fold.season,
        "starter_count": len(starters),
        **diagnostics,
    }


def _measure(arguments: argparse.Namespace, config: SquadShadowConfig) -> dict[str, object]:
    refuse_the_holdout(STUDY_SEASONS)
    manifest = load_residual_source_manifest(
        arguments.residual_table,
        arguments.residual_manifest,
        expect_model_name=MODEL_NAME,
        expect_model_version=IN_SEASON_MODEL_VERSION,
        expect_feature_contract_version=IN_SEASON_FEATURE_CONTRACT_VERSION,
    )
    panel = load_panel_without_the_holdout(arguments.archive_root)
    components = load_component_outcomes(arguments.archive_root, loaded_seasons(panel))
    residuals = pd.read_csv(arguments.residual_table)
    decisions = tuple(
        decision
        for season in STUDY_SEASONS
        for decision in walk_forward_decision_points(
            panel,
            seasons=(season,),
            min_prior_gameweeks_in_season=MIN_PRIOR_GAMEWEEKS_IN_SEASON,
        )
    )
    provide = _projection_provider(panel, decisions)
    provenance = PredictionProvenance(
        model_name=MODEL_NAME,
        model_version=IN_SEASON_MODEL_VERSION,
        feature_contract_version=IN_SEASON_FEATURE_CONTRACT_VERSION,
        training_cutoff="pre_fold_projection",
        training_data_fingerprint=manifest.table_sha256,
    )
    development = eligible_development_folds(
        build_squad_folds(
            panel, residuals, provide, seasons=(*SCREENING_SEASONS, VALIDATION_SEASON)
        ),
        config,
    )
    sensitivity = build_squad_folds(panel, residuals, provide, seasons=(SENSITIVITY_SEASON,))
    frozen_history = frozen_history_fold_ids(residuals)

    reading_frames: list[pd.DataFrame] = []
    diagnostic_rows: list[dict[str, object]] = []
    for fold, history_ids in (
        *((fold, fold.prior_fold_ids) for fold in development),
        *((fold, frozen_history) for fold in sensitivity),
    ):
        readings, diagnostic = _read_fold(
            fold, residuals, components, history_ids, provenance, config
        )
        reading_frames.append(readings)
        diagnostic_rows.append(diagnostic)
    readings = pd.concat(reading_frames, ignore_index=True)
    diagnostics = pd.DataFrame(diagnostic_rows)
    reconcile_population(readings, diagnostics, _recorded_population())
    for component in COMPONENTS:
        diagnostics[f"surprise_{component}"] = [
            float(cast(Mapping[str, float], value)[component])
            for value in diagnostics["component_surprises"]
        ]
    by_season: dict[str, dict[str, object]] = {}
    for season in STUDY_SEASONS:
        by_season[season] = summarise(
            readings.loc[readings["season"].astype(str).eq(season)],
            diagnostics.loc[diagnostics["season"].astype(str).eq(season)],
        )
    sensitivity_arms = cast(
        Mapping[str, Mapping[str, float | None]], by_season[SENSITIVITY_SEASON]["arms"]
    )
    replay = control_replay(sensitivity_arms["control"])
    _require(
        bool(replay["reproduced"]),
        "the component control does not reproduce the recorded Phase 2 result.",
    )
    return {
        "classification": classify(by_season[VALIDATION_SEASON], by_season[SENSITIVITY_SEASON]),
        "classification_population": VALIDATION_SEASON,
        "control_replay": replay,
        "season_sensitivity": by_season,
        "pooled": summarise(readings, diagnostics),
        "fold_universe": {
            "total_folds": int(readings["fold_id"].nunique()),
            "seasons": list(STUDY_SEASONS),
        },
        "panel_seasons_loaded": list(loaded_seasons(panel)),
        "component_rows": len(components),
        "residual_source": {
            "export_label": manifest.export_label,
            "table_sha256": manifest.table_sha256,
            "model_identity": f"{manifest.model_name}/{manifest.model_version}",
        },
        "panel_rows": len(panel),
    }


def main() -> int:
    arguments = _parse_arguments()
    started = datetime.now(UTC)
    config = SquadShadowConfig()
    revision, _ = _git_revision()
    dirty = _tree_dirty_ignoring(arguments.json_output)
    print(f"Study       {CONTRACT_VERSION}")
    print(f"Validate    {VALIDATION_SEASON}   Sensitivity {SENSITIVITY_SEASON}")
    print(f"Commit      {revision} (tree dirty: {str(dirty).lower()})")
    if dirty:
        print("\nRefused: the working tree carries changes this study did not write.")
        return 1
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            measured = _measure(arguments, config)
        except (
            DataSourceError,
            ResidualSourceError,
            ShadowReportError,
            SquadShadowError,
            OSError,
            ValueError,
        ) as error:
            print(f"\nRefused: {error}")
            return 1
    completed = datetime.now(UTC)
    panel_rows = cast(int, measured.pop("panel_rows"))
    metadata = artifact_metadata(
        panel_rows=panel_rows,
        created_utc=started.isoformat(timespec="seconds"),
        history_seasons=cast(Sequence[str], measured["panel_seasons_loaded"]),
    )
    document: dict[str, object] = {
        "contract_version": CONTRACT_VERSION,
        "created_utc": metadata["created_utc"],
        "study": "fixed selected-XI exact score-component attribution",
        "measurement_only": True,
        "promotion_eligible": False,
        "development_reuse_exploratory": True,
        "independent_confirmation": False,
        "locked_holdout_accessed": False,
        "source_artifact_digests": _digests(),
        "execution": {
            "started_at_utc": started.isoformat(timespec="seconds"),
            "completed_at_utc": completed.isoformat(timespec="seconds"),
            "elapsed_seconds": (completed - started).total_seconds(),
            "deterministic_seed": config.scenario_seed,
            "warnings": _recorded_warnings(caught),
        },
        "provenance": {
            **{
                str(key): value
                for key, value in cast(Mapping[object, object], metadata["provenance"]).items()
            },
            "repository_commit": revision,
            "working_tree_dirty": "false",
            **declared_parameters(config, shift_points=FROZEN_SHIFT_POINTS),
            "components": list(COMPONENTS),
            "component_formula": "fpl_fixture_score_components_v1",
            "fixture_duplicate_policy": "keep_first_element_round_fixture",
            "minimum_player_history": MIN_PLAYER_HISTORY,
            "identity_tolerance": IDENTITY_TOLERANCE,
            "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
            "bootstrap_confidence_level": CONFIDENCE_LEVEL,
            "bootstrap_seed": BOOTSTRAP_SEED,
        },
        "environment": metadata["environment"],
        **measured,
    }
    try:
        outcome = write_document_once(document, arguments.json_output)
    except ShadowReportError as error:
        print(f"\nRefused: {error}")
        return 1
    print(f"\nFolds       {measured['fold_universe']['total_folds']}")  # type: ignore[index]
    print(f"Class       {measured['classification']}")
    print(f"Wrote       {arguments.json_output} ({outcome})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

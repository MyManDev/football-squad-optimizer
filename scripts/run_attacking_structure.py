"""Run the pre-registered attacking downside structure diagnostic."""

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
from scripts.run_component_attribution import (
    _recorded_population,
    load_component_outcomes,
    reconcile_population,
)
from scripts.run_tail_diagnostic import (
    MODEL_NAME,
    _projection_provider,
    _recorded_warnings,
    _tree_dirty_ignoring,
)

from squadopt.backtest.splits import walk_forward_decision_points
from squadopt.data.errors import DataSourceError
from squadopt.evaluation.scoring import score_realized_squad_points
from squadopt.experiments.attacking_structure import (
    CONTRACT_VERSION,
    MARGINAL_EQUIVALENCE_BOUNDS,
    build_fold_metrics,
    classify,
    summarise,
)
from squadopt.experiments.component_attribution import (
    COMPONENTS,
    IDENTITY_TOLERANCE,
    MIN_PLAYER_HISTORY,
    _fold_order,
    _history_pool,
    attribute_fold,
)
from squadopt.experiments.component_attribution import (
    summarise as summarise_components,
)
from squadopt.experiments.residual_manifest import (
    ResidualSourceError,
    load_residual_source_manifest,
)
from squadopt.experiments.shadow_calibration import BOOTSTRAP_SEED, CONFIDENCE_LEVEL
from squadopt.experiments.shadow_report import ShadowReportError, write_document_once
from squadopt.experiments.shadow_squad_calibration import (
    BOOTSTRAP_RESAMPLES,
    FIT_SEASONS,
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

PHASE2H_ARTIFACT: Final = REPOSITORY_ROOT / "docs" / "phase2_component_attribution.json"
PHASE2H_SHA256: Final = "4023b06b637f3968e762cf7af3b0a9d7b0f45334d8be61d4a0603c1cbe96a3f8"
SOURCE_ARTIFACTS: Final = (
    REPOSITORY_ROOT / "docs" / "shadow_calibration_squad.json",
    REPOSITORY_ROOT / "docs" / "phase2_marginal_downside_sources.json",
    REPOSITORY_ROOT / "docs" / "phase2_projection_conditional_returns.json",
    PHASE2H_ARTIFACT,
)
DEFAULT_OUTPUT: Final = REPOSITORY_ROOT / "docs" / "phase2_attacking_structure.json"


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--residual-table", type=Path, required=True)
    parser.add_argument("--residual-manifest", type=Path, required=True)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def _digests() -> dict[str, str]:
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in SOURCE_ARTIFACTS}


def _phase2h_document() -> Mapping[str, object]:
    _require(
        hashlib.sha256(PHASE2H_ARTIFACT.read_bytes()).hexdigest() == PHASE2H_SHA256,
        "the Phase 2H artifact does not match the pre-registered source.",
    )
    document = json.loads(PHASE2H_ARTIFACT.read_text(encoding="utf-8"))
    _require(isinstance(document, Mapping), "the Phase 2H artifact must be a JSON object.")
    _require(
        document.get("contract_version") == "phase2_component_attribution_v1",
        "the Phase 2H artifact has an unexpected contract version.",
    )
    _require(
        document.get("locked_holdout_accessed") is False,
        "the Phase 2H artifact reports locked-holdout access.",
    )
    return cast(Mapping[str, object], document)


def _blank_history_pool(
    history: pd.DataFrame, *, player_id: object, position: str
) -> tuple[pd.DataFrame, str]:
    completed = history.loc[history["minutes"].astype("int64").ge(60)]
    _require(not completed.empty, "completed-appearance attacking history is empty.")
    return _history_pool(completed, player_id=player_id, position=position)


def _attacking_player_rows(
    starters: pd.DataFrame,
    target_components: pd.DataFrame,
    history_components: pd.DataFrame,
    history_fold_ids: Sequence[str],
    component_diagnostics: Mapping[str, object],
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Build player rows from the same decision used by component attribution."""

    _require(
        len(starters) == 11 and starters["player_id"].is_unique,
        "attacking structure requires eleven unique starters.",
    )
    _require(
        {"fold_id", "season", "player_id", "team_id", "position", "weight"}.issubset(
            starters.columns
        ),
        "attacking structure starter rows are incomplete.",
    )
    _require(
        starters["fold_id"].nunique() == 1 and starters["season"].nunique() == 1,
        "attacking structure starters must belong to one fold and season.",
    )
    target_fold = str(starters["fold_id"].iloc[0])
    target_season = str(starters["season"].iloc[0])
    allowed = {str(value) for value in history_fold_ids}
    _require(bool(allowed) and len(allowed) == len(history_fold_ids), "history folds repeat.")
    _require(
        all(_fold_order(fold_id) < _fold_order(target_fold) for fold_id in allowed),
        "attacking history contains a target or future fold.",
    )
    history = history_components.loc[history_components["fold_id"].astype(str).isin(allowed)]
    _require(
        {str(value) for value in history["fold_id"]} == allowed,
        "attacking history is missing a declared fold.",
    )
    _require(target_fold not in allowed, "the target fold cannot enter attacking history.")
    _require(
        bool(
            history.apply(
                lambda row: str(row["fold_id"]).startswith(f"{row['season']}-"), axis=1
            ).all()
        ),
        "attacking history season and fold labels disagree.",
    )
    if target_season == SENSITIVITY_SEASON:
        _require(
            set(history["season"].astype(str)).issubset(set(FIT_SEASONS)),
            "sensitivity attacking history is not frozen at the end of fit seasons.",
        )
    targets = target_components.loc[
        target_components["fold_id"].astype(str).eq(target_fold)
        & target_components["player_id"].isin(set(starters["player_id"]))
    ]
    _require(
        targets["player_id"].is_unique and set(targets["player_id"]) == set(starters["player_id"]),
        "attacking outcomes must cover every starter exactly once.",
    )
    joined = starters.merge(
        targets.loc[:, ["player_id", "position", "minutes", "fixture_count", "attacking"]],
        on="player_id",
        how="left",
        suffixes=("", "_outcome"),
        validate="one_to_one",
    )
    _require(
        bool(joined["position"].astype(str).eq(joined["position_outcome"].astype(str)).all()),
        "starter and attacking-outcome positions disagree.",
    )

    player_rows: list[dict[str, object]] = []
    weighted_surprise = 0.0
    source_counts = {"player_position": 0, "position": 0, "pooled": 0, "ineligible": 0}
    fixture_counts: dict[str, int] = {}
    history_pool_fixture_counts: dict[str, int] = {}
    for row in joined.itertuples(index=False):
        position = str(row.position)
        phase2h_pool, _ = _history_pool(history, player_id=row.player_id, position=position)
        phase2h_mean = float(phase2h_pool["attacking"].astype("float64").mean())
        weight = float(cast(float, row.weight))
        attacking = float(cast(float, row.attacking))
        weighted_surprise += weight * (attacking - phase2h_mean)
        completed = int(cast(int, row.minutes)) >= 60
        source = "ineligible"
        probability = float("nan")
        if completed:
            blank_pool, source = _blank_history_pool(
                history, player_id=row.player_id, position=position
            )
            probability = float(blank_pool["attacking"].astype("float64").eq(0.0).mean())
            for value, count in blank_pool["fixture_count"].astype("int64").value_counts().items():
                key = str(value)
                history_pool_fixture_counts[key] = history_pool_fixture_counts.get(key, 0) + int(
                    count
                )
        source_counts[source] += 1
        fixture_key = str(int(cast(int, row.fixture_count)))
        fixture_counts[fixture_key] = fixture_counts.get(fixture_key, 0) + 1
        player_rows.append(
            {
                "fold_id": target_fold,
                "season": target_season,
                "player_id": row.player_id,
                "team_id": row.team_id,
                "completed_appearance": int(completed),
                "attacking_blank": int(completed and attacking == 0.0),
                "blank_probability": probability,
                "history_source": source,
                "minutes": int(cast(int, row.minutes)),
                "fixture_count": int(cast(int, row.fixture_count)),
                "is_captain": int(weight == 2.0),
                "attacking_points": attacking,
            }
        )
    recorded_surprises = cast(Mapping[str, float], component_diagnostics["component_surprises"])
    _require(
        math.isclose(
            weighted_surprise,
            float(recorded_surprises["attacking"]),
            rel_tol=0.0,
            abs_tol=IDENTITY_TOLERANCE,
        ),
        f"{target_fold}: player attacking surprise does not reproduce Phase 2H.",
    )
    return pd.DataFrame(player_rows), {
        "fold_id": target_fold,
        "season": target_season,
        "weighted_attacking_surprise": weighted_surprise,
        "history_source_counts": source_counts,
        "fixture_counts": fixture_counts,
        "history_pool_fixture_counts": history_pool_fixture_counts,
    }


def _read_fold(
    fold: SquadFold,
    residuals: pd.DataFrame,
    components: pd.DataFrame,
    history_fold_ids: Sequence[str],
    provenance: PredictionProvenance,
    config: SquadShadowConfig,
) -> tuple[pd.DataFrame, dict[str, object], pd.DataFrame, dict[str, object]]:
    decision = optimize_squad_once(fold, config)
    starter_ids = decision.starting_xi["player_id"].tolist()
    _require(
        len(starter_ids) == 11 and len(set(starter_ids)) == 11,
        "a fold needs eleven unique starters.",
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
    starters = projection_rows.loc[
        starter_ids, ["team_id", "position", "expected_points"]
    ].reset_index()
    starters.insert(0, "fold_id", fold.fold_id)
    starters.insert(1, "season", fold.season)
    starters["weight"] = [
        2.0 if player_id == captain_id else 1.0 for player_id in starters["player_id"]
    ]
    target = components.loc[components["fold_id"].astype(str).eq(fold.fold_id)]
    readings, component_diagnostics = attribute_fold(
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
    player_rows, attacking_diagnostics = _attacking_player_rows(
        starters, target, components, history_fold_ids, component_diagnostics
    )
    _require(
        int(player_rows["is_captain"].sum()) == 1,
        f"{fold.fold_id}: attacking rows must contain one captain.",
    )
    return (
        readings,
        {
            "fold_id": fold.fold_id,
            "season": fold.season,
            "starter_count": len(starters),
            **component_diagnostics,
        },
        player_rows,
        attacking_diagnostics,
    )


def _reconcile_phase2h(
    measured: Mapping[str, Mapping[str, object]], recorded: Mapping[str, object]
) -> None:
    recorded_seasons = cast(Mapping[str, Mapping[str, object]], recorded["season_sensitivity"])
    for season in STUDY_SEASONS:
        current = measured[season]
        prior = recorded_seasons[season]
        current_arms = cast(Mapping[str, Mapping[str, object]], current["arms"])
        prior_arms = cast(Mapping[str, Mapping[str, object]], prior["arms"])
        current_components = cast(Mapping[str, Mapping[str, object]], current["components"])
        prior_components = cast(Mapping[str, Mapping[str, object]], prior["components"])
        for key in (
            "fold_count",
            "mean_probability_integral_transform",
            "below_lower_quantile_rate",
            "mean_realized_score",
            "mean_scenario_score",
        ):
            _require(
                math.isclose(
                    float(cast(float, current_arms["control"][key])),
                    float(cast(float, prior_arms["control"][key])),
                    rel_tol=0.0,
                    abs_tol=1e-12,
                ),
                f"{season}: the control does not reproduce Phase 2H {key}.",
            )
        _require(
            math.isclose(
                float(cast(float, current_components["attacking"]["mean_surprise"])),
                float(cast(float, prior_components["attacking"]["mean_surprise"])),
                rel_tol=0.0,
                abs_tol=1e-12,
            ),
            f"{season}: attacking surprise does not reproduce Phase 2H.",
        )


def _observation_summary(rows: pd.DataFrame, diagnostics: pd.DataFrame) -> dict[str, object]:
    sources = {"player_position": 0, "position": 0, "pooled": 0, "ineligible": 0}
    for source, count in rows["history_source"].astype(str).value_counts().items():
        sources[str(source)] = int(count)
    fixtures: dict[str, int] = {}
    for value, count in rows["fixture_count"].astype("int64").value_counts().sort_index().items():
        fixtures[str(value)] = int(count)
    history_fixtures: dict[str, int] = {}
    for value in diagnostics["history_pool_fixture_counts"]:
        _require(isinstance(value, Mapping), "history fixture counts must be mappings.")
        for fixture_count, count in cast(Mapping[str, int], value).items():
            history_fixtures[fixture_count] = history_fixtures.get(fixture_count, 0) + int(count)
    minutes = rows["minutes"].astype("int64")
    return {
        "selected_starters": len(rows),
        "completed_appearance_starters": int(minutes.ge(60).sum()),
        "partial_appearance_starters": int(minutes.between(1, 59).sum()),
        "zero_minute_starters": int(minutes.eq(0).sum()),
        "history_source_counts": sources,
        "target_fixture_counts": fixtures,
        "effective_history_pool_fixture_counts": history_fixtures,
    }


def _measure(arguments: argparse.Namespace, config: SquadShadowConfig) -> dict[str, object]:
    refuse_the_holdout(STUDY_SEASONS)
    phase2h = _phase2h_document()
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
    component_diagnostics: list[dict[str, object]] = []
    player_frames: list[pd.DataFrame] = []
    attacking_diagnostics: list[dict[str, object]] = []
    metric_rows: list[dict[str, object]] = []
    for fold, history_ids in (
        *((fold, fold.prior_fold_ids) for fold in development),
        *((fold, frozen_history) for fold in sensitivity),
    ):
        readings, component_diag, players, attacking_diag = _read_fold(
            fold, residuals, components, history_ids, provenance, config
        )
        reading_frames.append(readings)
        component_diagnostics.append(component_diag)
        player_frames.append(players)
        attacking_diagnostics.append(attacking_diag)
        metric_rows.append(build_fold_metrics(players))

    readings = pd.concat(reading_frames, ignore_index=True)
    component_frame = pd.DataFrame(component_diagnostics)
    player_rows = pd.concat(player_frames, ignore_index=True)
    attacking_frame = pd.DataFrame(attacking_diagnostics)
    metrics = pd.DataFrame(metric_rows)
    reconcile_population(readings, component_frame, _recorded_population())
    for component in COMPONENTS:
        component_frame[f"surprise_{component}"] = [
            float(cast(Mapping[str, float], value)[component])
            for value in component_frame["component_surprises"]
        ]
    component_by_season: dict[str, Mapping[str, object]] = {}
    structure_by_season: dict[str, Mapping[str, object]] = {}
    observations_by_season: dict[str, Mapping[str, object]] = {}
    for season in STUDY_SEASONS:
        component_by_season[season] = summarise_components(
            readings.loc[readings["season"].astype(str).eq(season)],
            component_frame.loc[component_frame["season"].astype(str).eq(season)],
        )
        structure_by_season[season] = summarise(
            metrics.loc[metrics["season"].astype(str).eq(season)]
        )
        observations_by_season[season] = _observation_summary(
            player_rows.loc[player_rows["season"].astype(str).eq(season)],
            attacking_frame.loc[attacking_frame["season"].astype(str).eq(season)],
        )
    _reconcile_phase2h(component_by_season, phase2h)
    sensitivity_arms = cast(
        Mapping[str, Mapping[str, float | None]],
        component_by_season[SENSITIVITY_SEASON]["arms"],
    )
    replay = control_replay(sensitivity_arms["control"])
    _require(bool(replay["reproduced"]), "the control does not reproduce Phase 2H.")
    _require(
        len(attacking_diagnostics) == int(cast(int, _recorded_population()["total_folds"])),
        "attacking diagnostics do not cover every fold.",
    )
    return {
        "classification": classify(
            structure_by_season[VALIDATION_SEASON],
            structure_by_season[SENSITIVITY_SEASON],
        ),
        "classification_population": VALIDATION_SEASON,
        "control_replay": replay,
        "phase2h_reconciliation": {
            "artifact_sha256": hashlib.sha256(PHASE2H_ARTIFACT.read_bytes()).hexdigest(),
            "per_fold_attacking_surprise_reproduced": True,
            "seasonal_control_and_attacking_summaries_reproduced": True,
        },
        "season_sensitivity": structure_by_season,
        "observation_support": observations_by_season,
        "pooled": summarise(metrics),
        "fold_universe": {
            "total_folds": int(metrics["fold_id"].nunique()),
            "starter_rows": len(player_rows),
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
        "study": "fixed selected-XI attacking downside structure",
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
            "attacking_event": "player_gameweek_minutes_gte_60_and_attacking_points_eq_0",
            "minimum_player_history": MIN_PLAYER_HISTORY,
            "marginal_equivalence_bounds": list(MARGINAL_EQUIVALENCE_BOUNDS),
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
    fold_universe = cast(Mapping[str, object], measured["fold_universe"])
    print(f"\nFolds       {fold_universe['total_folds']}")
    print(f"Class       {measured['classification']}")
    print(f"Wrote       {arguments.json_output} ({outcome})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

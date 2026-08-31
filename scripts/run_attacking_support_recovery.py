"""Run the pre-registered attacking support-recovery diagnostic."""

import argparse
import hashlib
import json
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
from scripts.run_attacking_hurdle import (
    PHASE2I_SHA256,
    _assert_nested_replay,
    _hurdle_player_rows,
    _observation_summary,
    _phase2i_document,
    _read_pinned_residual_table,
    _require_pinned_residual_manifest,
)
from scripts.run_attacking_hurdle import (
    SOURCE_ARTIFACTS as PHASE2J_SOURCE_ARTIFACTS,
)
from scripts.run_attacking_structure import (
    PHASE2H_SHA256,
    _phase2h_document,
    _read_fold,
    _reconcile_phase2h,
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
from squadopt.experiments.attacking_hurdle import build_fold_reading as build_hurdle_reading
from squadopt.experiments.attacking_hurdle import classify as classify_hurdle
from squadopt.experiments.attacking_hurdle import summarise as summarise_hurdle
from squadopt.experiments.attacking_structure import build_fold_metrics
from squadopt.experiments.attacking_structure import classify as classify_structure
from squadopt.experiments.attacking_structure import summarise as summarise_structure
from squadopt.experiments.attacking_support_recovery import (
    BOOTSTRAP_RESAMPLES,
    BOOTSTRAP_SEED,
    CONFIDENCE_LEVEL,
    CONTRACT_VERSION,
    FILL_TARGET,
    IDENTITY_TOLERANCE,
    MIN_POSITIVE_RETURNS,
    build_fold_reading,
    classify,
    recover_player_rows,
    summarise,
)
from squadopt.experiments.component_attribution import COMPONENTS
from squadopt.experiments.component_attribution import summarise as summarise_components
from squadopt.experiments.residual_manifest import (
    ResidualSourceError,
    load_residual_source_manifest,
)
from squadopt.experiments.shadow_report import ShadowReportError, write_document_once
from squadopt.experiments.shadow_squad_calibration import (
    HISTORY_SEASONS,
    MIN_PRIOR_GAMEWEEKS_IN_SEASON,
    SquadShadowConfig,
    SquadShadowError,
    _require,
    build_squad_folds,
    declared_parameters,
    frozen_history_fold_ids,
    load_panel_without_the_holdout,
    loaded_seasons,
)
from squadopt.experiments.tail_diagnostic import (
    FROZEN_SHIFT_POINTS,
    SCREENING_SEASONS,
    SENSITIVITY_SEASON,
    STUDY_SEASONS,
    VALIDATION_SEASON,
    control_replay,
    eligible_development_folds,
    refuse_the_holdout,
)
from squadopt.prediction import PredictionProvenance
from squadopt.prediction.in_season import (
    IN_SEASON_FEATURE_CONTRACT_VERSION,
    IN_SEASON_MODEL_VERSION,
)

PHASE2J_ARTIFACT: Final = REPOSITORY_ROOT / "docs" / "phase2_attacking_hurdle.json"
PHASE2J_SHA256: Final = "5b3dc676bbc21642cd027823d90f43c97e27297d06764660bcf8d627666f3f2b"
SOURCE_ARTIFACTS: Final = (*PHASE2J_SOURCE_ARTIFACTS, PHASE2J_ARTIFACT)
DEFAULT_OUTPUT: Final = REPOSITORY_ROOT / "docs" / "phase2_attacking_support_recovery.json"


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--residual-table", type=Path, required=True)
    parser.add_argument("--residual-manifest", type=Path, required=True)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def _digests() -> dict[str, str]:
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in SOURCE_ARTIFACTS}


def _residual_input_digests(arguments: argparse.Namespace) -> dict[str, str]:
    return {
        "residual_table": hashlib.sha256(arguments.residual_table.read_bytes()).hexdigest(),
        "residual_manifest": hashlib.sha256(arguments.residual_manifest.read_bytes()).hexdigest(),
    }


def _phase2j_document() -> Mapping[str, object]:
    _require(
        hashlib.sha256(PHASE2J_ARTIFACT.read_bytes()).hexdigest() == PHASE2J_SHA256,
        "the Phase 2J artifact does not match the pre-registered source.",
    )
    document = json.loads(PHASE2J_ARTIFACT.read_text(encoding="utf-8"))
    _require(isinstance(document, Mapping), "the Phase 2J artifact must be a JSON object.")
    _require(
        document.get("contract_version") == "phase2_attacking_hurdle_v1",
        "the Phase 2J artifact has an unexpected contract version.",
    )
    _require(
        document.get("locked_holdout_accessed") is False,
        "the Phase 2J artifact reports locked-holdout access.",
    )
    return cast(Mapping[str, object], document)


def _background_reference(
    history: pd.DataFrame, *, player_id: object, position: str
) -> tuple[float, int, str]:
    """Return the frozen target-excluded reference for one sparse Phase 2H pool."""

    positives = history.loc[
        history["attacking"].astype("float64").gt(0.0)
        & history["player_id"].astype(str).ne(str(player_id))
    ]
    position_rows = positives.loc[positives["position"].astype(str).eq(position)]
    if len(position_rows) >= MIN_POSITIVE_RETURNS:
        return (
            float(position_rows["attacking"].astype("float64").mean()),
            len(position_rows),
            "position_target_excluded",
        )
    if len(positives) >= MIN_POSITIVE_RETURNS:
        return (
            float(positives["attacking"].astype("float64").mean()),
            len(positives),
            "pooled_target_excluded",
        )
    return float("nan"), 0, "unsupported_sparse_reference"


def _recovery_player_rows(
    hurdle_rows: pd.DataFrame,
    target_components: pd.DataFrame,
    history_components: pd.DataFrame,
    history_fold_ids: Sequence[str],
) -> pd.DataFrame:
    """Attach the one frozen sparse reference, then apply the recovery contract."""

    target_fold = str(hurdle_rows["fold_id"].iloc[0])
    target = target_components.loc[
        target_components["fold_id"].astype(str).eq(target_fold)
        & target_components["player_id"].isin(set(hurdle_rows["player_id"]))
    ]
    _require(
        target["player_id"].is_unique and set(target["player_id"]) == set(hurdle_rows["player_id"]),
        "recovery outcomes must cover every starter exactly once.",
    )
    rows = hurdle_rows.merge(
        target.loc[:, ["player_id", "position"]],
        on="player_id",
        how="left",
        validate="one_to_one",
    )
    allowed = {str(value) for value in history_fold_ids}
    history = history_components.loc[history_components["fold_id"].astype(str).isin(allowed)]
    _require(
        {str(value) for value in history["fold_id"]} == allowed,
        "support-recovery history is missing a declared fold.",
    )
    _require(
        not bool(history.duplicated(["fold_id", "player_id"]).any()),
        "support-recovery history repeats an aggregated player-gameweek.",
    )

    background_means: list[float] = []
    background_counts: list[int] = []
    background_sources: list[str] = []
    for row in rows.itertuples(index=False):
        positive_count = int(cast(int, row.history_positive_returns))
        if 1 <= positive_count < MIN_POSITIVE_RETURNS:
            mean, count, source = _background_reference(
                history, player_id=row.player_id, position=str(row.position)
            )
        else:
            mean, count, source = float("nan"), 0, ""
        background_means.append(mean)
        background_counts.append(count)
        background_sources.append(source)
    rows["recovery_background_mean"] = background_means
    rows["recovery_background_positive_returns"] = background_counts
    rows["recovery_background_source"] = background_sources
    return cast(pd.DataFrame, recover_player_rows(rows.drop(columns="position")))


def _support_summary(rows: pd.DataFrame, readings: pd.DataFrame) -> dict[str, object]:
    """Return the declared support, fill, identity and descriptive diagnostics."""

    _require(
        "carrier_supported" in rows.columns,
        "Phase 2J starter support is missing from recovered rows.",
    )
    supported = rows["supported"].astype(bool)
    eligible = readings["eligible"].astype(bool)
    history_counts = rows["history_positive_returns"].astype("int64")
    fill_rows = rows.loc[history_counts.lt(MIN_POSITIVE_RETURNS)]
    fill = fill_rows["fill_fraction"].astype("float64")
    alignment = rows.loc[supported, "alignment_gap"].astype("float64")
    player_errors = rows.loc[supported, "identity_error"].astype("float64").abs()
    fold_errors = pd.to_numeric(readings.loc[eligible, "identity_error"], errors="coerce")

    def bins() -> dict[str, int]:
        return {
            "zero": int(history_counts.eq(0).sum()),
            "one_to_four": int(history_counts.between(1, 4).sum()),
            "five_plus": int(history_counts.ge(MIN_POSITIVE_RETURNS).sum()),
        }

    source_by_bin: dict[str, dict[str, int]] = {}
    for row in rows.loc[:, ["support_bin", "reference_source"]].itertuples(index=False):
        support_bin = str(row.support_bin)
        source = str(row.reference_source)
        sources = source_by_bin.setdefault(support_bin, {})
        sources[source] = sources.get(source, 0) + 1

    original_eligible = rows.groupby("fold_id", sort=False)["carrier_supported"].all()
    recovered_by_fold = rows.groupby("fold_id", sort=False)["recovered_sparse"].max().astype(bool)
    current_eligible = readings.set_index("fold_id")["eligible"].astype(bool)
    _require(
        current_eligible.index.is_unique
        and set(current_eligible.index.astype(str)) == set(original_eligible.index.astype(str)),
        "support readings do not cover every recovered fold exactly once.",
    )
    current_eligible.index = current_eligible.index.astype(str)
    original_eligible.index = original_eligible.index.astype(str)
    recovered_by_fold.index = recovered_by_fold.index.astype(str)
    current_eligible = current_eligible.reindex(original_eligible.index)
    _require(
        not bool((original_eligible & ~current_eligible).any()),
        "support recovery made a Phase 2J-eligible fold ineligible.",
    )
    newly_eligible = ~original_eligible & current_eligible

    minutes = rows["minutes"].astype("int64")
    return {
        "selected_starters": len(rows),
        "supported_starters": int(supported.sum()),
        "unsupported_starters": int((~supported).sum()),
        "eligible_folds": int(eligible.sum()),
        "excluded_folds": int((~eligible).sum()),
        "recovered_sparse_starters": int(rows["recovered_sparse"].astype("int64").sum()),
        "folds_with_recovered_sparse_starter": int(recovered_by_fold.sum()),
        "newly_eligible_folds": int(newly_eligible.sum()),
        "original_positive_support": bins(),
        "reference_source_counts": {
            str(source): int(count)
            for source, count in rows["reference_source"].astype(str).value_counts().items()
        },
        "reference_source_by_support_bin": source_by_bin,
        "fill_fraction": {
            "count": len(fill),
            "mean": float(fill.mean()) if len(fill) else None,
            "maximum": float(fill.max()) if len(fill) else None,
        },
        "alignment_gap": {
            "signed_mean": float(alignment.mean()) if len(alignment) else None,
            "mean_absolute": float(alignment.abs().mean()) if len(alignment) else None,
            "maximum_absolute": float(alignment.abs().max()) if len(alignment) else None,
        },
        "target_positive_returns": int(rows["target_positive"].astype("int64").sum()),
        "target_zero_returns": int((~rows["target_positive"].astype(bool)).sum()),
        "minutes": {
            "zero": int(minutes.eq(0).sum()),
            "partial_1_to_59": int(minutes.between(1, 59).sum()),
            "completed_60_plus": int(minutes.ge(60).sum()),
        },
        "target_fixture_counts": {
            str(value): int(count)
            for value, count in rows["fixture_count"].astype("int64").value_counts().items()
        },
        "maximum_absolute_player_identity_error": (
            float(player_errors.max()) if len(player_errors) else None
        ),
        "maximum_absolute_fold_identity_error": (
            float(fold_errors.abs().max()) if len(fold_errors) else None
        ),
    }


def _measure(arguments: argparse.Namespace, config: SquadShadowConfig) -> dict[str, object]:
    refuse_the_holdout(STUDY_SEASONS)
    phase2h = _phase2h_document()
    phase2i = _phase2i_document()
    phase2j = _phase2j_document()
    phase2h_residual = phase2h.get("residual_source")
    _require(isinstance(phase2h_residual, Mapping), "Phase 2H residual provenance is missing.")
    expected_residual_sha256 = str(
        cast(Mapping[str, object], phase2h_residual).get("table_sha256", "")
    )
    _require(len(expected_residual_sha256) == 64, "Phase 2H residual digest is invalid.")
    phase2j_residual = phase2j.get("residual_source")
    _require(
        isinstance(phase2j_residual, Mapping)
        and cast(Mapping[str, object], phase2j_residual).get("table_sha256")
        == expected_residual_sha256,
        "Phase 2J does not name the pinned Phase 2H residual export.",
    )
    _require_pinned_residual_manifest(arguments.residual_manifest, expected_residual_sha256)
    manifest = load_residual_source_manifest(
        arguments.residual_table,
        arguments.residual_manifest,
        expect_model_name=MODEL_NAME,
        expect_model_version=IN_SEASON_MODEL_VERSION,
        expect_feature_contract_version=IN_SEASON_FEATURE_CONTRACT_VERSION,
    )
    _require(
        manifest.table_sha256 == expected_residual_sha256,
        "the loaded residual export does not reproduce Phase 2H.",
    )
    residuals = _read_pinned_residual_table(arguments.residual_table, expected_residual_sha256)
    panel = load_panel_without_the_holdout(arguments.archive_root)
    _require(
        loaded_seasons(panel) == HISTORY_SEASONS,
        "loaded panel seasons differ from the requested history seasons.",
    )
    components = load_component_outcomes(arguments.archive_root, loaded_seasons(panel))
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
    structure_metrics: list[dict[str, object]] = []
    hurdle_players: list[pd.DataFrame] = []
    hurdle_diagnostics: list[dict[str, object]] = []
    hurdle_readings: list[dict[str, object]] = []
    recovery_players: list[pd.DataFrame] = []
    recovery_readings: list[dict[str, object]] = []
    for fold, history_ids in (
        *((fold, fold.prior_fold_ids) for fold in development),
        *((fold, frozen_history) for fold in sensitivity),
    ):
        readings, component_diag, phase2i_rows, _ = _read_fold(
            fold, residuals, components, history_ids, provenance, config
        )
        target = components.loc[components["fold_id"].astype(str).eq(fold.fold_id)]
        hurdle_rows, hurdle_diag = _hurdle_player_rows(
            phase2i_rows, target, components, history_ids, component_diag
        )
        recovered_rows = _recovery_player_rows(hurdle_rows, target, components, history_ids)
        control = readings.loc[readings["arm"].astype(str).eq("control")]
        _require(len(control) == 1, f"{fold.fold_id}: the control reading is not unique.")
        control_row = control.iloc[0]
        score = float(control_row["realized_score"])
        lower = float(control_row["lower_quantile_score"])
        tail = bool(control_row["below_lower_quantile"])
        hurdle_readings.append(build_hurdle_reading(hurdle_rows, score, lower, tail))
        recovery_readings.append(build_fold_reading(recovered_rows, score, lower, tail))
        reading_frames.append(readings)
        component_diagnostics.append(component_diag)
        structure_metrics.append(build_fold_metrics(phase2i_rows))
        hurdle_players.append(hurdle_rows)
        hurdle_diagnostics.append(hurdle_diag)
        recovery_players.append(recovered_rows)

    readings = pd.concat(reading_frames, ignore_index=True)
    component_frame = pd.DataFrame(component_diagnostics)
    structure_frame = pd.DataFrame(structure_metrics)
    hurdle_player_frame = pd.concat(hurdle_players, ignore_index=True)
    hurdle_diagnostic_frame = pd.DataFrame(hurdle_diagnostics)
    hurdle_reading_frame = pd.DataFrame(hurdle_readings)
    recovery_player_frame = pd.concat(recovery_players, ignore_index=True)
    recovery_reading_frame = pd.DataFrame(recovery_readings)
    reconcile_population(readings, component_frame, _recorded_population())
    for component in COMPONENTS:
        component_frame[f"surprise_{component}"] = [
            float(cast(Mapping[str, float], value)[component])
            for value in component_frame["component_surprises"]
        ]

    component_by_season: dict[str, Mapping[str, object]] = {}
    structure_by_season: dict[str, Mapping[str, object]] = {}
    hurdle_by_season: dict[str, Mapping[str, object]] = {}
    hurdle_support_by_season: dict[str, Mapping[str, object]] = {}
    recovery_by_season: dict[str, Mapping[str, object]] = {}
    recovery_support_by_season: dict[str, Mapping[str, object]] = {}
    recorded_structure = cast(Mapping[str, Mapping[str, object]], phase2i["season_sensitivity"])
    recorded_hurdle = cast(Mapping[str, Mapping[str, object]], phase2j["season_sensitivity"])
    recorded_hurdle_support = cast(
        Mapping[str, Mapping[str, object]], phase2j["observation_support"]
    )
    for season in STUDY_SEASONS:
        season_readings = readings.loc[readings["season"].astype(str).eq(season)]
        season_components = component_frame.loc[component_frame["season"].astype(str).eq(season)]
        component_by_season[season] = summarise_components(season_readings, season_components)
        structure_by_season[season] = summarise_structure(
            structure_frame.loc[structure_frame["season"].astype(str).eq(season)]
        )
        _assert_nested_replay(
            structure_by_season[season], recorded_structure[season], path=f"phase2i.{season}"
        )
        hurdle_by_season[season] = summarise_hurdle(
            hurdle_reading_frame.loc[hurdle_reading_frame["season"].astype(str).eq(season)]
        )
        hurdle_support_by_season[season] = _observation_summary(
            hurdle_player_frame.loc[hurdle_player_frame["season"].astype(str).eq(season)],
            hurdle_diagnostic_frame.loc[hurdle_diagnostic_frame["season"].astype(str).eq(season)],
        )
        _assert_nested_replay(
            hurdle_by_season[season], recorded_hurdle[season], path=f"phase2j.{season}"
        )
        _assert_nested_replay(
            hurdle_support_by_season[season],
            recorded_hurdle_support[season],
            path=f"phase2j.support.{season}",
        )
        recovered_season_readings = recovery_reading_frame.loc[
            recovery_reading_frame["season"].astype(str).eq(season)
        ]
        recovered_season_players = recovery_player_frame.loc[
            recovery_player_frame["season"].astype(str).eq(season)
        ]
        recovery_by_season[season] = summarise(recovered_season_readings)
        recovery_support_by_season[season] = _support_summary(
            recovered_season_players, recovered_season_readings
        )

    _reconcile_phase2h(component_by_season, phase2h)
    _require(
        classify_structure(
            structure_by_season[VALIDATION_SEASON], structure_by_season[SENSITIVITY_SEASON]
        )
        == phase2i["classification"],
        "the Phase 2I classification does not replay.",
    )
    _require(
        classify_hurdle(hurdle_by_season[VALIDATION_SEASON], hurdle_by_season[SENSITIVITY_SEASON])
        == phase2j["classification"],
        "the Phase 2J classification does not replay.",
    )
    _assert_nested_replay(
        {
            "folds_by_season": {
                season: int(recovery_reading_frame["season"].astype(str).eq(season).sum())
                for season in STUDY_SEASONS
            },
            "total_folds": int(recovery_reading_frame["fold_id"].nunique()),
            "starter_rows": len(recovery_player_frame),
            "seasons": list(STUDY_SEASONS),
        },
        phase2j["fold_universe"],
        path="phase2j.fold_universe",
    )
    sensitivity_arms = cast(
        Mapping[str, Mapping[str, float | None]],
        component_by_season[SENSITIVITY_SEASON]["arms"],
    )
    replay = control_replay(sensitivity_arms["control"])
    _require(bool(replay["reproduced"]), "the control does not reproduce Phase 2H.")
    return {
        "classification": classify(
            recovery_by_season[VALIDATION_SEASON], recovery_by_season[SENSITIVITY_SEASON]
        ),
        "classification_population": VALIDATION_SEASON,
        "control_replay": replay,
        "source_reconciliation": {
            "phase2h_artifact_sha256": PHASE2H_SHA256,
            "phase2i_artifact_sha256": PHASE2I_SHA256,
            "phase2j_artifact_sha256": PHASE2J_SHA256,
            "phase2h_per_fold_attacking_surprise_reproduced": True,
            "phase2h_seasonal_summaries_reproduced": True,
            "phase2i_seasonal_structure_reproduced": True,
            "phase2i_classification_reproduced": True,
            "phase2j_support_and_summaries_reproduced": True,
            "phase2j_classification_reproduced": True,
        },
        "phase2j_observation_support": hurdle_support_by_season,
        "season_sensitivity": recovery_by_season,
        "observation_support": recovery_support_by_season,
        "fold_universe": {
            "folds_by_season": {
                season: int(recovery_reading_frame["season"].astype(str).eq(season).sum())
                for season in STUDY_SEASONS
            },
            "total_folds": int(recovery_reading_frame["fold_id"].nunique()),
            "starter_rows": len(recovery_player_frame),
            "seasons": list(STUDY_SEASONS),
        },
        "panel_seasons_loaded": list(loaded_seasons(panel)),
        "panel_seasons_requested": list(HISTORY_SEASONS),
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
            source_digests = _digests()
            residual_input_digests = _residual_input_digests(arguments)
            measured = _measure(arguments, config)
            completed_revision, _ = _git_revision()
            _require(
                completed_revision == revision, "the repository commit changed during measurement."
            )
            _require(
                not _tree_dirty_ignoring(arguments.json_output),
                "the working tree changed during the measurement.",
            )
            _require(_digests() == source_digests, "a source artifact changed during measurement.")
            _require(
                _residual_input_digests(arguments) == residual_input_digests,
                "a residual input changed during measurement.",
            )
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
    metadata_provenance = cast(Mapping[str, object], metadata["provenance"])
    _require(
        metadata_provenance.get("repository_commit") == revision
        and metadata_provenance.get("working_tree_dirty") is False,
        "artifact metadata does not describe the clean measured revision.",
    )
    document: dict[str, object] = {
        "contract_version": CONTRACT_VERSION,
        "created_utc": metadata["created_utc"],
        "study": "fixed selected-XI attacking support recovery",
        "measurement_only": True,
        "promotion_eligible": False,
        "development_reuse_exploratory": True,
        "independent_confirmation": False,
        "locked_holdout_accessed": False,
        "source_artifact_digests": source_digests,
        "residual_input_digests": residual_input_digests,
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
                for key, value in cast(Mapping[object, object], metadata_provenance).items()
            },
            **declared_parameters(config, shift_points=FROZEN_SHIFT_POINTS),
            "attacking_event": "player_gameweek_attacking_points_gt_0",
            "minimum_positive_history": MIN_POSITIVE_RETURNS,
            "fill_target": FILL_TARGET,
            "support_recovery_rule": "fill_to_five_position_then_pooled_target_excluded",
            "identity_tolerance": IDENTITY_TOLERANCE,
            "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
            "bootstrap_confidence_level": CONFIDENCE_LEVEL,
            "bootstrap_seed": BOOTSTRAP_SEED,
        },
        "environment": metadata["environment"],
        **measured,
    }
    try:
        final_revision, _ = _git_revision()
        _require(
            final_revision == revision
            and not _tree_dirty_ignoring(arguments.json_output)
            and _digests() == source_digests,
            "the measured repository state changed before artifact publication.",
        )
        _require(
            _residual_input_digests(arguments) == residual_input_digests,
            "a residual input changed before artifact publication.",
        )
        outcome = write_document_once(document, arguments.json_output)
    except (ShadowReportError, SquadShadowError, OSError, ValueError) as error:
        print(f"\nRefused: {error}")
        return 1
    fold_universe = cast(Mapping[str, object], measured["fold_universe"])
    print(f"\nFolds       {fold_universe['total_folds']}")
    print(f"Class       {measured['classification']}")
    print(f"Wrote       {arguments.json_output} ({outcome})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Run the pre-registered attacking occurrence/severity attribution."""

import argparse
import hashlib
import json
import math
import sys
import warnings
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Final, cast

import pandas as pd
from scripts._experiment_cli import (
    DEFAULT_ARCHIVE_ROOT,
    REPOSITORY_ROOT,
    _git_revision,
    artifact_metadata,
)
from scripts.run_attacking_structure import (
    PHASE2H_SHA256,
    _phase2h_document,
    _read_fold,
    _reconcile_phase2h,
)
from scripts.run_attacking_structure import (
    SOURCE_ARTIFACTS as PHASE2I_SOURCE_ARTIFACTS,
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
from squadopt.experiments.attacking_hurdle import (
    BOOTSTRAP_RESAMPLES,
    BOOTSTRAP_SEED,
    CONFIDENCE_LEVEL,
    CONTRACT_VERSION,
    MIN_POSITIVE_RETURNS,
    build_fold_reading,
    decompose_player_rows,
    summarise,
)
from squadopt.experiments.attacking_hurdle import (
    IDENTITY_TOLERANCE as HURDLE_IDENTITY_TOLERANCE,
)
from squadopt.experiments.attacking_hurdle import (
    classify as classify_hurdle,
)
from squadopt.experiments.attacking_structure import (
    build_fold_metrics,
)
from squadopt.experiments.attacking_structure import (
    classify as classify_structure,
)
from squadopt.experiments.attacking_structure import (
    summarise as summarise_structure,
)
from squadopt.experiments.component_attribution import (
    COMPONENTS,
    IDENTITY_TOLERANCE,
    _fold_order,
    _history_pool,
)
from squadopt.experiments.component_attribution import (
    summarise as summarise_components,
)
from squadopt.experiments.residual_manifest import (
    ResidualSourceError,
    load_residual_source_manifest,
)
from squadopt.experiments.shadow_report import ShadowReportError, write_document_once
from squadopt.experiments.shadow_squad_calibration import (
    FIT_SEASONS,
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

PHASE2I_ARTIFACT: Final = REPOSITORY_ROOT / "docs" / "phase2_attacking_structure.json"
PHASE2I_SHA256: Final = "0ee1dafa085b7ce417ec7be603c30ad299a015cc5fe34d676353a9592b834fc2"
SOURCE_ARTIFACTS: Final = (*PHASE2I_SOURCE_ARTIFACTS, PHASE2I_ARTIFACT)
DEFAULT_OUTPUT: Final = REPOSITORY_ROOT / "docs" / "phase2_attacking_hurdle.json"


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--residual-table", type=Path, required=True)
    parser.add_argument("--residual-manifest", type=Path, required=True)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def _digests() -> dict[str, str]:
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in SOURCE_ARTIFACTS}


def _phase2i_document() -> Mapping[str, object]:
    _require(
        hashlib.sha256(PHASE2I_ARTIFACT.read_bytes()).hexdigest() == PHASE2I_SHA256,
        "the Phase 2I artifact does not match the pre-registered source.",
    )
    document = json.loads(PHASE2I_ARTIFACT.read_text(encoding="utf-8"))
    _require(isinstance(document, Mapping), "the Phase 2I artifact must be a JSON object.")
    _require(
        document.get("contract_version") == "phase2_attacking_structure_v1",
        "the Phase 2I artifact has an unexpected contract version.",
    )
    _require(
        document.get("locked_holdout_accessed") is False,
        "the Phase 2I artifact reports locked-holdout access.",
    )
    return cast(Mapping[str, object], document)


def _require_pinned_residual_manifest(manifest_path: Path, expected_sha256: str) -> None:
    """Refuse a substituted residual export before any table byte is consumed."""

    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    _require(isinstance(document, Mapping), "the residual manifest must be a JSON object.")
    _require(
        document.get("table_sha256") == expected_sha256,
        "the residual manifest does not name the Phase 2H residual export.",
    )


def _read_pinned_residual_table(table_path: Path, expected_sha256: str) -> pd.DataFrame:
    """Parse exactly the residual bytes whose digest was validated."""

    payload = table_path.read_bytes()
    _require(
        hashlib.sha256(payload).hexdigest() == expected_sha256,
        "the residual table changed after validation.",
    )
    return pd.read_csv(BytesIO(payload))


def _positive_fallback(history: pd.DataFrame, *, position: str) -> tuple[pd.DataFrame | None, str]:
    positives = history.loc[history["attacking"].astype("float64").gt(0.0)]
    position_rows = positives.loc[positives["position"].astype(str).eq(position)]
    if len(position_rows) >= MIN_POSITIVE_RETURNS:
        return position_rows, "position_zero_positive_fallback"
    if len(positives) >= MIN_POSITIVE_RETURNS:
        return positives, "pooled_zero_positive_fallback"
    return None, "unsupported_zero_positive_history"


def _hurdle_player_rows(
    phase2i_rows: pd.DataFrame,
    target_components: pd.DataFrame,
    history_components: pd.DataFrame,
    history_fold_ids: Sequence[str],
    component_diagnostics: Mapping[str, object],
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Build exact occurrence/severity rows from one already-read fold decision."""

    required = {
        "fold_id",
        "season",
        "player_id",
        "is_captain",
        "attacking_points",
        "minutes",
        "fixture_count",
    }
    _require(required.issubset(phase2i_rows.columns), "Phase 2I player rows are incomplete.")
    _require(
        len(phase2i_rows) == 11 and phase2i_rows["player_id"].is_unique,
        "a hurdle fold requires eleven unique starters.",
    )
    _require(
        int(phase2i_rows["is_captain"].sum()) == 1,
        "a hurdle fold requires one captain.",
    )
    _require(
        phase2i_rows["fold_id"].nunique() == 1 and phase2i_rows["season"].nunique() == 1,
        "hurdle player rows must belong to one fold and season.",
    )
    target_fold = str(phase2i_rows["fold_id"].iloc[0])
    target_season = str(phase2i_rows["season"].iloc[0])
    allowed = tuple(str(value) for value in history_fold_ids)
    _require(
        bool(allowed) and len(allowed) == len(set(allowed)),
        "hurdle history folds repeat or are empty.",
    )
    _require(
        all(_fold_order(fold_id) < _fold_order(target_fold) for fold_id in allowed),
        "hurdle history contains a target or future fold.",
    )
    history = history_components.loc[history_components["fold_id"].astype(str).isin(set(allowed))]
    _require(
        {str(value) for value in history["fold_id"]} == set(allowed),
        "hurdle history is missing a declared fold.",
    )
    _require(
        not bool(history.duplicated(["fold_id", "player_id"]).any()),
        "hurdle history repeats an aggregated player-gameweek.",
    )
    _require(
        bool(
            history.apply(
                lambda row: str(row["fold_id"]).startswith(f"{row['season']}-"), axis=1
            ).all()
        ),
        "hurdle history season and fold labels disagree.",
    )
    if target_season == SENSITIVITY_SEASON:
        _require(
            set(history["season"].astype(str)).issubset(set(FIT_SEASONS)),
            "sensitivity hurdle history is not frozen at the end of fit seasons.",
        )
    targets = target_components.loc[
        target_components["fold_id"].astype(str).eq(target_fold)
        & target_components["player_id"].isin(set(phase2i_rows["player_id"]))
    ]
    _require(
        targets["player_id"].is_unique
        and set(targets["player_id"]) == set(phase2i_rows["player_id"]),
        "hurdle outcomes must cover every starter exactly once.",
    )
    joined = phase2i_rows.merge(
        targets.loc[:, ["player_id", "position", "attacking"]],
        on="player_id",
        how="left",
        validate="one_to_one",
    )
    _require(
        bool(
            joined["attacking_points"]
            .astype("float64")
            .eq(joined["attacking"].astype("float64"))
            .all()
        ),
        "Phase 2I and component attacking outcomes disagree.",
    )

    rows: list[dict[str, object]] = []
    unsupported_reasons: dict[str, int] = {}
    zero_fallback_rows = 0
    for row in joined.itertuples(index=False):
        position = str(row.position)
        pool, phase2h_source = _history_pool(history, player_id=row.player_id, position=position)
        attacks = pool["attacking"].astype("float64")
        positives = pool.loc[attacks.gt(0.0), "attacking"].astype("float64")
        probability = len(positives) / len(pool)
        severity_source = f"phase2h_{phase2h_source}"
        used_fallback = False
        if len(positives):
            positive_mean = float(positives.mean())
            reference_positive_returns = len(positives)
            if len(positives) < MIN_POSITIVE_RETURNS:
                unsupported_reasons["phase2h_pool_has_1_to_4_positives"] = (
                    unsupported_reasons.get("phase2h_pool_has_1_to_4_positives", 0) + 1
                )
        else:
            fallback, severity_source = _positive_fallback(history, position=position)
            used_fallback = fallback is not None
            zero_fallback_rows += int(used_fallback)
            positive_mean = (
                float(fallback["attacking"].astype("float64").mean())
                if fallback is not None
                else float("nan")
            )
            reference_positive_returns = len(fallback) if fallback is not None else 0
            if fallback is None:
                unsupported_reasons["zero_positive_history_has_no_supported_fallback"] = (
                    unsupported_reasons.get("zero_positive_history_has_no_supported_fallback", 0)
                    + 1
                )
        historical_mean = float(attacks.mean())
        attacking = float(cast(float, row.attacking))
        weight = 2.0 if bool(row.is_captain) else 1.0
        rows.append(
            {
                "fold_id": target_fold,
                "season": target_season,
                "player_id": row.player_id,
                "weight": weight,
                "attacking_points": attacking,
                "history_attacking_mean": historical_mean,
                "occurrence_probability": probability,
                "positive_mean": positive_mean,
                "history_positive_returns": len(positives),
                "severity_reference_positive_returns": reference_positive_returns,
                "history_count": len(pool),
                "phase2h_source": phase2h_source,
                "severity_source": severity_source,
                "zero_positive_history": int(len(positives) == 0),
                "zero_positive_fallback": int(used_fallback),
                "minutes": int(cast(int, row.minutes)),
                "fixture_count": int(cast(int, row.fixture_count)),
                "is_captain": int(bool(row.is_captain)),
            }
        )
    result = decompose_player_rows(pd.DataFrame(rows))
    fold_surprise = float(result["attacking_surprise"].sum())
    hurdle_total = float(result["occurrence"].sum() + result["severity"].sum())
    recorded = cast(Mapping[str, float], component_diagnostics["component_surprises"])
    _require(
        math.isclose(
            fold_surprise,
            float(recorded["attacking"]),
            rel_tol=0.0,
            abs_tol=IDENTITY_TOLERANCE,
        )
        and (
            not bool(result["supported"].all())
            or math.isclose(
                hurdle_total,
                fold_surprise,
                rel_tol=0.0,
                abs_tol=HURDLE_IDENTITY_TOLERANCE,
            )
        ),
        f"{target_fold}: fold hurdle terms do not reproduce Phase 2H attacking surprise.",
    )
    supported_errors = result.loc[result["supported"], "identity_error"].abs()
    return result, {
        "fold_id": target_fold,
        "season": target_season,
        "eligible": bool(result["supported"].astype(bool).all()),
        "unsupported_reasons": unsupported_reasons,
        "zero_positive_fallback_rows": zero_fallback_rows,
        "maximum_absolute_player_identity_error": (
            float(supported_errors.max()) if len(supported_errors) else None
        ),
        "fold_identity_error": (
            hurdle_total - fold_surprise if bool(result["supported"].all()) else None
        ),
    }


def _assert_nested_replay(current: object, recorded: object, *, path: str) -> None:
    if isinstance(current, Mapping) and isinstance(recorded, Mapping):
        _require(set(current) == set(recorded), f"{path}: replay keys differ.")
        for key in current:
            _assert_nested_replay(current[key], recorded[key], path=f"{path}.{key}")
        return
    if isinstance(current, list) and isinstance(recorded, list):
        _require(len(current) == len(recorded), f"{path}: replay list lengths differ.")
        for index, (left, right) in enumerate(zip(current, recorded, strict=True)):
            _assert_nested_replay(left, right, path=f"{path}[{index}]")
        return
    if type(current) in {int, float} and type(recorded) in {int, float}:
        _require(
            math.isclose(
                float(cast(float | int, current)),
                float(cast(float | int, recorded)),
                rel_tol=0.0,
                abs_tol=1e-12,
            ),
            f"{path}: replay numeric values differ.",
        )
        return
    _require(current == recorded, f"{path}: replay values differ.")


def _observation_summary(rows: pd.DataFrame, diagnostics: pd.DataFrame) -> dict[str, object]:
    def support_bins(column: str) -> dict[str, int]:
        values = rows[column].astype("int64")
        return {
            "zero": int(values.eq(0).sum()),
            "one_to_four": int(values.between(1, 4).sum()),
            "five_plus": int(values.ge(MIN_POSITIVE_RETURNS).sum()),
        }

    source_counts: dict[str, int] = {}
    for source, count in rows["severity_source"].astype(str).value_counts().items():
        source_counts[str(source)] = int(count)
    player_reasons: dict[str, int] = {}
    fold_reasons: dict[str, int] = {}
    for value in diagnostics["unsupported_reasons"]:
        _require(isinstance(value, Mapping), "unsupported reasons must be mappings.")
        for reason, count in cast(Mapping[str, int], value).items():
            player_reasons[reason] = player_reasons.get(reason, 0) + int(count)
            fold_reasons[reason] = fold_reasons.get(reason, 0) + 1
    minutes = rows["minutes"].astype("int64")
    player_errors = pd.to_numeric(
        diagnostics["maximum_absolute_player_identity_error"], errors="coerce"
    ).dropna()
    fold_errors = pd.to_numeric(diagnostics["fold_identity_error"], errors="coerce").dropna()
    return {
        "selected_starters": len(rows),
        "supported_starters": int(rows["supported"].sum()),
        "unsupported_starters": int((~rows["supported"].astype(bool)).sum()),
        "target_positive_returns": int(rows["target_positive"].sum()),
        "target_zero_returns": int((~rows["target_positive"].astype(bool)).sum()),
        "eligible_folds": int(diagnostics["eligible"].sum()),
        "excluded_folds": int((~diagnostics["eligible"].astype(bool)).sum()),
        "unsupported_player_reasons": player_reasons,
        "excluded_fold_reasons": fold_reasons,
        "severity_source_counts": source_counts,
        "history_positive_support": support_bins("history_positive_returns"),
        "severity_reference_positive_support": support_bins("severity_reference_positive_returns"),
        "zero_positive_history_rows": int(rows["zero_positive_history"].sum()),
        "zero_positive_fallback_rows": int(rows["zero_positive_fallback"].sum()),
        "zero_positive_fallback_folds": int(
            diagnostics["zero_positive_fallback_rows"].astype("int64").gt(0).sum()
        ),
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
    phase2h_residual = phase2h.get("residual_source")
    _require(isinstance(phase2h_residual, Mapping), "Phase 2H residual provenance is missing.")
    expected_residual_sha256 = str(
        cast(Mapping[str, object], phase2h_residual).get("table_sha256", "")
    )
    _require(len(expected_residual_sha256) == 64, "Phase 2H residual digest is invalid.")
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
    hurdle_player_frames: list[pd.DataFrame] = []
    hurdle_diagnostics: list[dict[str, object]] = []
    hurdle_readings: list[dict[str, object]] = []
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
        control = readings.loc[readings["arm"].astype(str).eq("control")]
        _require(len(control) == 1, f"{fold.fold_id}: the control reading is not unique.")
        control_row = control.iloc[0]
        hurdle_readings.append(
            build_fold_reading(
                hurdle_rows,
                control_realized_score=float(control_row["realized_score"]),
                lower_quantile_score=float(control_row["lower_quantile_score"]),
                control_below_q10=bool(control_row["below_lower_quantile"]),
            )
        )
        reading_frames.append(readings)
        component_diagnostics.append(component_diag)
        structure_metrics.append(build_fold_metrics(phase2i_rows))
        hurdle_player_frames.append(hurdle_rows)
        hurdle_diagnostics.append(hurdle_diag)

    readings = pd.concat(reading_frames, ignore_index=True)
    component_frame = pd.DataFrame(component_diagnostics)
    structure_frame = pd.DataFrame(structure_metrics)
    hurdle_players = pd.concat(hurdle_player_frames, ignore_index=True)
    hurdle_diagnostic_frame = pd.DataFrame(hurdle_diagnostics)
    hurdle_reading_frame = pd.DataFrame(hurdle_readings)
    recorded_population = _recorded_population()
    reconcile_population(readings, component_frame, recorded_population)
    for component in COMPONENTS:
        component_frame[f"surprise_{component}"] = [
            float(cast(Mapping[str, float], value)[component])
            for value in component_frame["component_surprises"]
        ]

    component_by_season: dict[str, Mapping[str, object]] = {}
    structure_by_season: dict[str, Mapping[str, object]] = {}
    hurdle_by_season: dict[str, Mapping[str, object]] = {}
    support_by_season: dict[str, Mapping[str, object]] = {}
    recorded_structure = cast(Mapping[str, Mapping[str, object]], phase2i["season_sensitivity"])
    for season in STUDY_SEASONS:
        component_by_season[season] = summarise_components(
            readings.loc[readings["season"].astype(str).eq(season)],
            component_frame.loc[component_frame["season"].astype(str).eq(season)],
        )
        structure_by_season[season] = summarise_structure(
            structure_frame.loc[structure_frame["season"].astype(str).eq(season)]
        )
        _assert_nested_replay(
            structure_by_season[season],
            recorded_structure[season],
            path=f"phase2i.{season}",
        )
        hurdle_by_season[season] = summarise(
            hurdle_reading_frame.loc[hurdle_reading_frame["season"].astype(str).eq(season)]
        )
        support_by_season[season] = _observation_summary(
            hurdle_players.loc[hurdle_players["season"].astype(str).eq(season)],
            hurdle_diagnostic_frame.loc[hurdle_diagnostic_frame["season"].astype(str).eq(season)],
        )
    _reconcile_phase2h(component_by_season, phase2h)
    _require(
        classify_structure(
            structure_by_season[VALIDATION_SEASON],
            structure_by_season[SENSITIVITY_SEASON],
        )
        == phase2i["classification"],
        "the Phase 2I classification does not replay.",
    )
    sensitivity_arms = cast(
        Mapping[str, Mapping[str, float | None]],
        component_by_season[SENSITIVITY_SEASON]["arms"],
    )
    replay = control_replay(sensitivity_arms["control"])
    _require(bool(replay["reproduced"]), "the control does not reproduce Phase 2H.")
    return {
        "classification": classify_hurdle(
            hurdle_by_season[VALIDATION_SEASON], hurdle_by_season[SENSITIVITY_SEASON]
        ),
        "classification_population": VALIDATION_SEASON,
        "control_replay": replay,
        "source_reconciliation": {
            "phase2h_artifact_sha256": PHASE2H_SHA256,
            "phase2i_artifact_sha256": PHASE2I_SHA256,
            "phase2h_per_fold_attacking_surprise_reproduced": True,
            "phase2h_seasonal_summaries_reproduced": True,
            "phase2i_seasonal_structure_reproduced": True,
        },
        "season_sensitivity": hurdle_by_season,
        "observation_support": support_by_season,
        "fold_universe": {
            "folds_by_season": {
                season: int(hurdle_reading_frame["season"].astype(str).eq(season).sum())
                for season in STUDY_SEASONS
            },
            "total_folds": int(hurdle_reading_frame["fold_id"].nunique()),
            "starter_rows": len(hurdle_players),
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
            measured = _measure(arguments, config)
            completed_revision, _ = _git_revision()
            _require(
                completed_revision == revision,
                "the repository commit changed during the measurement.",
            )
            _require(
                not _tree_dirty_ignoring(arguments.json_output),
                "the working tree changed during the measurement.",
            )
            _require(
                _digests() == source_digests,
                "a source artifact changed during the measurement.",
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
        "study": "fixed selected-XI attacking occurrence/severity attribution",
        "measurement_only": True,
        "promotion_eligible": False,
        "development_reuse_exploratory": True,
        "independent_confirmation": False,
        "locked_holdout_accessed": False,
        "source_artifact_digests": source_digests,
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
            "identity_tolerance": HURDLE_IDENTITY_TOLERANCE,
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

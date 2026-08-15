"""Out-of-sample residual export for the deterministic control regime.

The residual-export contract (`oos_residual_export_v1`) was written for the
prediction-side handoff, but the uncertainty, scenario, and risk layers need the same
artifact for the operational control regime — and that regime is fully reproducible
from this repository. This module builds it: per-player predicted-versus-realized
rows for every chronological development fold, using only the leakage-safe shifted
feature chain the control already runs on.

This export is control-regime evidence for the calibration layers. It is not, and
must not be labeled as, the #43 candidate export that remains the prediction side's
deliverable.
"""

from collections.abc import Mapping
from typing import Final

import pandas as pd

from squadopt.backtest import realized_points_at, season_ranks, walk_forward_decision_points
from squadopt.experiments.config import ExperimentExecutionError
from squadopt.experiments.policy_objective import (
    EVALUATION_OBJECTIVE_VERSION,
    PolicyObjectiveConfig,
)
from squadopt.features import build_feature_dataset
from squadopt.prediction import (
    FEATURE_GENERATION_CONTRACT_VERSION,
    FormWindowMapping,
    build_projection_table,
)
from squadopt.preflight import RESIDUAL_EXPORT_COLUMNS, RESIDUAL_EXPORT_CONTRACT_VERSION

CONTROL_CANDIDATE_LABEL: Final = "deterministic_baseline_control"
CONTROL_MODEL_NAME: Final = "deterministic_baseline"
CONTROL_TRAINING_CONTRACT_VERSION: Final = "deterministic_baseline_no_training_v1"


def control_model_version(form_window: int) -> str:
    """Return the control model version string for one frozen form window."""

    if form_window < 1:
        raise ExperimentExecutionError("form_window must be a positive integer.")
    return f"form_window_{form_window:02d}_v1"


def build_control_residual_table(
    panel: pd.DataFrame,
    config: PolicyObjectiveConfig | None = None,
    *,
    form_window: int = 5,
) -> pd.DataFrame:
    """Build the contract-ordered residual table for the control regime.

    Every row pairs one fold's pre-match projection with the realized points read
    only after that decision point. Projections and outcomes derive from the same
    target-gameweek rows, so the pairing is complete by construction; a player the
    panel does not carry at a gameweek is absent from both sides rather than being
    filled in.
    """

    settings = PolicyObjectiveConfig() if config is None else config
    if not isinstance(settings, PolicyObjectiveConfig):
        raise ExperimentExecutionError("config must be a PolicyObjectiveConfig instance.")
    if not isinstance(panel, pd.DataFrame):
        raise ExperimentExecutionError("panel must be a pandas DataFrame.")
    ranks = season_ranks(panel)
    unknown = sorted(set(settings.development_seasons) - set(ranks))
    if unknown:
        raise ExperimentExecutionError(
            f"Development seasons are absent from the panel: {unknown!r}."
        )
    last_rank = max(ranks[season] for season in settings.development_seasons)
    keep = panel["season"].map(lambda season: ranks[str(season)] <= last_rank)
    visible_panel = panel.loc[keep].copy(deep=True)
    decisions = walk_forward_decision_points(
        visible_panel,
        seasons=settings.development_seasons,
        min_prior_gameweeks_in_season=settings.min_prior_gameweeks_in_season,
    )
    if not decisions:
        raise ExperimentExecutionError(
            "No decision points remain for the requested development seasons."
        )
    mapping = FormWindowMapping(form_window=form_window)
    features = build_feature_dataset(
        visible_panel,
        config=mapping.feature_config,
        cross_season=settings.cross_season_config,
    )

    pieces: list[pd.DataFrame] = []
    for decision in decisions:
        projections = build_projection_table(
            features,
            season=decision.season,
            gameweek=decision.gameweek,
            config=mapping.projection_config,
        )
        realized = realized_points_at(visible_panel, decision)
        merged = projections.loc[:, ["player_id", "team_id", "position", "expected_points"]].merge(
            realized,
            on="player_id",
            how="left",
        )
        if bool(merged["total_points"].isna().any()):
            raise ExperimentExecutionError(
                f"Fold {decision.fold_id} projects players with no realized outcome; "
                "the export cannot invent realized points."
            )
        piece = pd.DataFrame(
            {
                "fold_id": decision.fold_id,
                "season": decision.season,
                "gameweek": decision.gameweek,
                "player_id": merged["player_id"],
                "team_id": merged["team_id"],
                "position": merged["position"],
                "predicted_points": merged["expected_points"].astype("float64"),
                "realized_points": merged["total_points"].astype("float64"),
            }
        )
        pieces.append(piece)

    table = pd.concat(pieces, ignore_index=True)
    table["residual"] = table["realized_points"] - table["predicted_points"]
    table = table.loc[:, list(RESIDUAL_EXPORT_COLUMNS)]
    return table.sort_values(["season", "gameweek", "player_id"], kind="stable", ignore_index=True)


def control_residual_manifest(
    table: pd.DataFrame,
    *,
    form_window: int,
    repository_commit: str,
    dataset_snapshot_id: str,
    table_sha256: str,
    created_at_utc: str,
    candidate_label: str = CONTROL_CANDIDATE_LABEL,
) -> Mapping[str, object]:
    """Return the manifest describing one control residual export.

    ``candidate_label`` names the regime for pairing; a second export produced with a
    different form window must carry a different label, because the pairing rule
    refuses two exports claiming the same regime.
    """

    if not isinstance(table, pd.DataFrame) or table.empty:
        raise ExperimentExecutionError("table must be a non-empty pandas DataFrame.")
    if not isinstance(candidate_label, str) or not candidate_label.strip():
        raise ExperimentExecutionError("candidate_label must be non-empty text.")
    return {
        "contract_version": RESIDUAL_EXPORT_CONTRACT_VERSION,
        "candidate_label": candidate_label.strip(),
        "model_name": CONTROL_MODEL_NAME,
        "model_version": control_model_version(form_window),
        "feature_contract_version": FEATURE_GENERATION_CONTRACT_VERSION,
        "training_contract_version": CONTROL_TRAINING_CONTRACT_VERSION,
        "evaluation_objective": EVALUATION_OBJECTIVE_VERSION,
        "development_seasons": sorted({str(season) for season in table["season"]}),
        "opening_gameweeks_included": bool((table["gameweek"] == 1).any()),
        "fold_count": int(table["fold_id"].nunique()),
        "row_count": len(table),
        "repository_commit": repository_commit,
        "dataset_snapshot_id": dataset_snapshot_id,
        "table_sha256": table_sha256,
        "created_at_utc": created_at_utc,
    }

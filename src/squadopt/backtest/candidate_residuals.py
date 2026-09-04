"""Out-of-sample residual export for a candidate prediction regime.

The control regime's export (`squadopt.experiments.control_residuals`) is the reference
half of the pairing. This module builds the candidate half for any projection builder
that returns a versioned ``PredictionSnapshot``, so the same code produces the
calendar-aware production export today and the #43 learned-rate export once it exists.

Two decisions are worth stating.

**Identity is read from the snapshot, never passed in.** The handoff checklist requires
the model, version, and feature-contract strings to be identical in the declaration, both
manifests, and every returned ``PredictionSnapshot``. Deriving the manifest from the
snapshots makes that true by construction rather than by careful copying, which is where
the last handoff drifted.

**The projection/outcome join is a left join that raises.** ``build_residual_history``
inner-joins, which would silently drop a player present on one side only. The export
contract forbids dropping unmatched rows precisely because it would change both the
error population and the decision population without saying so, and the control export
already takes the loud path — a pair produced by asymmetric join rules is not a pair.
"""

from collections.abc import Mapping, Sequence
from typing import Final

import pandas as pd

from squadopt.backtest.folds import ProjectionBuilder, build_walk_forward_folds
from squadopt.backtest.splits import BacktestConfigurationError, season_ranks
from squadopt.evaluation import EvaluationFold
from squadopt.preflight import RESIDUAL_EXPORT_COLUMNS, RESIDUAL_EXPORT_CONTRACT_VERSION

EVALUATION_OBJECTIVE_VERSION: Final = "single_gameweek_realized_squad_points_v1"

# Written precision for the projected values, and the reason there is one at all.
#
# Two owners regenerated this export at the same commit and recorded different
# `table_sha256` while every reported decimal agreed. The candidate fits a ridge system
# through LAPACK, which is not bit-identical across machines, and a sixteen-digit
# serialisation turns a last-bit difference into a different file. The control export has
# no linear solve and reproduced exactly, which is what isolated the cause.
#
# Nine decimals is measured, not chosen: at that precision no row of 101,447 moves under a
# relative perturbation of 1e-15, which is an order of magnitude above what double
# precision can produce. The measurement is `docs/export_precision.md`. It is also five
# orders below anything any report quotes, so it discards nothing a reader could notice.
PREDICTED_POINTS_DECIMALS: Final = 9
DEFAULT_DEVELOPMENT_SEASONS: Final = ("2021-22", "2022-23", "2023-24", "2024-25")

# The provenance fields the handoff checklist pins across declaration, manifests, and
# snapshots. Read from fold metadata, which `build_walk_forward_folds` fills only when a
# builder returns a real PredictionSnapshot.
IDENTITY_FIELDS: Final = (
    ("model_name", "prediction_model_name"),
    ("model_version", "prediction_model_version"),
    ("feature_contract_version", "prediction_feature_contract_version"),
)


def candidate_identity(folds: Sequence[EvaluationFold]) -> Mapping[str, str]:
    """Return the one model identity every fold's snapshot agrees on.

    A builder that returns a plain frame, or whose identity drifts between folds, is
    refused here rather than at the gate: an export whose rows came from two model
    versions cannot honestly carry one manifest.
    """

    if not folds:
        raise BacktestConfigurationError("folds must be a non-empty sequence.")

    identity: dict[str, str] = {}
    for field, metadata_key in IDENTITY_FIELDS:
        observed = {str(fold.metadata.get(metadata_key, "")) for fold in folds}
        if observed == {""}:
            raise BacktestConfigurationError(
                f"The candidate builder returned no {metadata_key!r}; a residual export "
                "requires a versioned PredictionSnapshot, not a plain DataFrame."
            )
        if len(observed) != 1:
            raise BacktestConfigurationError(
                f"Candidate {metadata_key!r} differs across folds: {sorted(observed)!r}. "
                "One export describes one model."
            )
        identity[field] = observed.pop()
    return identity


def round_for_export(table: pd.DataFrame) -> pd.DataFrame:
    """Round the projected values to the declared precision and rederive the residual.

    Applied at the serialisation boundary rather than inside a builder, because the
    precision belongs to the export contract and not to any one model: both halves of a
    pair must be written the same way or a reader comparing them row by row sees one side
    at nine decimals and the other at seventeen.

    The residual is recomputed from the *rounded* projection rather than derived from the
    unrounded one, so the identity `residual == realized_points - predicted_points` holds
    on the values a reader actually sees. It holds to within float64's representation of
    a nine-decimal number — measured at 3.6e-15 across 200,000 rows, with four fifths of
    them exact — not to the last bit, because a rounded decimal is not exactly
    representable in binary. Deriving the residual from the unrounded projection instead
    would leave a discrepancy near 1e-9, five orders worse and inside the range a reader
    might notice. Realized points are integral, so nothing is lost on that side.

    Returns an independent copy; the input is never modified.
    """

    if not isinstance(table, pd.DataFrame):
        raise BacktestConfigurationError("table must be a pandas DataFrame.")
    missing = [
        column for column in ("predicted_points", "realized_points") if column not in table.columns
    ]
    if missing:
        raise BacktestConfigurationError(f"table is missing columns: {missing!r}.")

    rounded = table.copy(deep=True)
    rounded["predicted_points"] = (
        rounded["predicted_points"].astype("float64").round(PREDICTED_POINTS_DECIMALS)
    )
    rounded["residual"] = (
        rounded["realized_points"].astype("float64") - rounded["predicted_points"]
    ).round(PREDICTED_POINTS_DECIMALS)
    return rounded


def _residual_rows(fold: EvaluationFold) -> pd.DataFrame:
    projections = fold.projections.loc[:, ["player_id", "team_id", "position", "expected_points"]]
    realized = fold.realized_points.loc[:, ["player_id", "total_points"]]
    merged = projections.merge(realized, on="player_id", how="left", validate="one_to_one")
    if bool(merged["total_points"].isna().any()):
        missing = merged.loc[merged["total_points"].isna(), "player_id"].tolist()
        raise BacktestConfigurationError(
            f"Fold {fold.fold_id} projects players with no realized outcome "
            f"({missing[:5]!r}); the export cannot invent realized points."
        )
    return pd.DataFrame(
        {
            "fold_id": fold.fold_id,
            "season": str(fold.metadata["season"]),
            "gameweek": int(str(fold.metadata["gameweek"])),
            "player_id": merged["player_id"],
            "team_id": merged["team_id"],
            "position": merged["position"],
            "predicted_points": merged["expected_points"].astype("float64"),
            "realized_points": merged["total_points"].astype("float64"),
        }
    )


def build_candidate_residual_table(
    panel: pd.DataFrame,
    projection_builder: ProjectionBuilder,
    *,
    seasons: Sequence[str] = DEFAULT_DEVELOPMENT_SEASONS,
    min_prior_gameweeks_in_season: int = 1,
) -> tuple[pd.DataFrame, Mapping[str, str]]:
    """Build one candidate's contract-ordered residual table and its model identity."""

    if not isinstance(panel, pd.DataFrame):
        raise BacktestConfigurationError("panel must be a pandas DataFrame.")
    if not callable(projection_builder):
        raise BacktestConfigurationError("projection_builder must be callable.")
    if min_prior_gameweeks_in_season < 1:
        raise BacktestConfigurationError(
            "min_prior_gameweeks_in_season must be at least 1; opening gameweeks are a "
            "separate evidence regime."
        )

    requested = tuple(seasons)
    ranks = season_ranks(panel)
    unknown = sorted(set(requested) - set(ranks))
    if unknown:
        raise BacktestConfigurationError(
            f"Development seasons are absent from the panel: {unknown!r}."
        )

    # Cut later seasons before any feature is built, so a locked-holdout row cannot
    # reach a shifted window even as carry-over history.
    last_rank = max(ranks[season] for season in requested)
    visible = panel.loc[panel["season"].map(lambda season: ranks[str(season)] <= last_rank)]

    folds = build_walk_forward_folds(
        visible,
        seasons=requested,
        min_prior_gameweeks_in_season=min_prior_gameweeks_in_season,
        projection_builder=projection_builder,
    )
    identity = candidate_identity(folds)

    table = round_for_export(pd.concat([_residual_rows(fold) for fold in folds], ignore_index=True))
    table = table.loc[:, list(RESIDUAL_EXPORT_COLUMNS)]
    return (
        table.sort_values(["season", "gameweek", "player_id"], kind="stable", ignore_index=True),
        identity,
    )


def candidate_residual_manifest(
    table: pd.DataFrame,
    identity: Mapping[str, str],
    *,
    candidate_label: str,
    training_contract_version: str,
    repository_commit: str,
    dataset_snapshot_id: str,
    table_sha256: str,
    created_at_utc: str,
) -> Mapping[str, object]:
    """Return the manifest describing one candidate residual export."""

    if not isinstance(table, pd.DataFrame) or table.empty:
        raise BacktestConfigurationError("table must be a non-empty pandas DataFrame.")
    for name, value in (
        ("candidate_label", candidate_label),
        ("training_contract_version", training_contract_version),
        ("repository_commit", repository_commit),
        ("dataset_snapshot_id", dataset_snapshot_id),
        ("table_sha256", table_sha256),
        ("created_at_utc", created_at_utc),
    ):
        if not isinstance(value, str) or not value.strip():
            raise BacktestConfigurationError(f"{name} must be non-empty text.")
    missing = [field for field, _ in IDENTITY_FIELDS if not str(identity.get(field, "")).strip()]
    if missing:
        raise BacktestConfigurationError(f"identity is missing {missing!r}.")

    return {
        "contract_version": RESIDUAL_EXPORT_CONTRACT_VERSION,
        "candidate_label": candidate_label.strip(),
        "model_name": identity["model_name"],
        "model_version": identity["model_version"],
        "feature_contract_version": identity["feature_contract_version"],
        "training_contract_version": training_contract_version.strip(),
        "evaluation_objective": EVALUATION_OBJECTIVE_VERSION,
        "development_seasons": sorted({str(season) for season in table["season"]}),
        "opening_gameweeks_included": bool((table["gameweek"] == 1).any()),
        "fold_count": int(table["fold_id"].nunique()),
        "row_count": len(table),
        "repository_commit": repository_commit.strip(),
        "dataset_snapshot_id": dataset_snapshot_id.strip(),
        "table_sha256": table_sha256.strip(),
        "created_at_utc": created_at_utc.strip(),
    }

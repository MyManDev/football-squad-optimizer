"""Conservative Top-100 evidence adjustment for the operational point handoff."""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from numbers import Integral
from types import MappingProxyType
from typing import Final

import pandas as pd

from squadopt.data.timestamps import as_instant
from squadopt.prediction.config import PredictionConfigurationError

ELITE_EVIDENCE_POLICY_VERSION: Final = "phase_c_operational_elite_policy_v1"
ELITE_EVIDENCE_MODEL_VERSION: Final = "in-season-carry-over-elite-top100-v1"
ELITE_EVIDENCE_FEATURE_CONTRACT_VERSION: Final = "in-season-carry-over-elite-top100-features-v1"
ELITE_COHORT_SIZE: Final = 100
ELITE_XI_SIZE: Final = 11
MAXIMUM_RELATIVE_UPLIFT: Final = 0.05

_PROJECTION_COLUMNS: Final = ("player_id", "expected_points")
_EVIDENCE_COLUMNS: Final = (
    "season",
    "target_gameweek",
    "captured_at_utc",
    "deadline_timestamp_utc",
    "player_id",
    "elite_cohort_size",
    "elite_members_observed",
    "elite_start_count_lag1",
    "elite_start_share_lag1",
    "elite_evidence_observed",
)


@dataclass(frozen=True, slots=True)
class EliteEvidenceAdjustment:
    """An independent adjusted projection and its audit diagnostics."""

    table: pd.DataFrame
    diagnostics: Mapping[str, object]


def _require_columns(frame: pd.DataFrame, columns: tuple[str, ...], label: str) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise PredictionConfigurationError(f"{label} is missing columns {missing!r}.")
    duplicates = frame.columns[frame.columns.duplicated()].tolist()
    if duplicates:
        raise PredictionConfigurationError(f"{label} repeats columns {duplicates!r}.")


def _single(frame: pd.DataFrame, column: str, label: str) -> object:
    values = frame[column].drop_duplicates().tolist()
    if len(values) != 1:
        raise PredictionConfigurationError(
            f"{label} {column!r} must contain exactly one value; found {values!r}."
        )
    return values[0]


def _require_integer_ids(frame: pd.DataFrame, label: str) -> None:
    invalid = [
        value
        for value in frame["player_id"].tolist()
        if isinstance(value, bool) or not isinstance(value, Integral)
    ]
    if invalid:
        raise PredictionConfigurationError(
            f"{label} player_id values must be non-boolean integers; "
            f"invalid examples: {invalid[:10]!r}."
        )


def apply_elite_evidence(
    projection: pd.DataFrame,
    evidence: pd.DataFrame,
    *,
    season: str,
    target_gameweek: int,
    deadline_timestamp_utc: str,
    decision_captured_at_utc: str,
) -> EliteEvidenceAdjustment:
    """Apply the frozen Top-100 XI-support rule to an in-season point projection.

    The elite signal is a lagged FPL selection frequency, not an appearance
    probability. It supplies a bounded relative uplift and never penalises a player.
    """

    if not isinstance(projection, pd.DataFrame) or not isinstance(evidence, pd.DataFrame):
        raise PredictionConfigurationError("projection and evidence must be pandas DataFrames.")
    _require_columns(projection, _PROJECTION_COLUMNS, "Projection")
    _require_columns(evidence, _EVIDENCE_COLUMNS, "Evidence")
    _require_integer_ids(projection, "Projection")
    _require_integer_ids(evidence, "Evidence")
    if projection.empty or evidence.empty:
        raise PredictionConfigurationError("Projection and evidence must contain player rows.")
    if projection["player_id"].duplicated().any() or evidence["player_id"].duplicated().any():
        raise PredictionConfigurationError(
            "Projection and evidence player_id values must be unique."
        )

    expected_context = {
        "season": season,
        "target_gameweek": target_gameweek,
        "deadline_timestamp_utc": deadline_timestamp_utc,
    }
    for column, expected in expected_context.items():
        actual = _single(evidence, column, "Evidence")
        if actual != expected:
            raise PredictionConfigurationError(
                f"Evidence {column} is {actual!r}; the decision requires {expected!r}."
            )
    evidence_captured_at = _single(evidence, "captured_at_utc", "Evidence")
    if not isinstance(evidence_captured_at, str):
        raise PredictionConfigurationError("Evidence captured_at_utc must be text.")
    if as_instant(evidence_captured_at) > as_instant(decision_captured_at_utc):
        raise PredictionConfigurationError(
            "Evidence was captured after the decision snapshot and cannot be used in its replay."
        )
    generated_at = evidence.attrs.get("generated_at_utc")
    if not isinstance(generated_at, str):
        raise PredictionConfigurationError("Evidence generated_at_utc provenance is required.")
    if as_instant(generated_at) > as_instant(decision_captured_at_utc):
        raise PredictionConfigurationError(
            "The evidence artifact was generated after the decision snapshot and cannot "
            "be used in its replay."
        )

    cohort = _single(evidence, "elite_cohort_size", "Evidence")
    observed = _single(evidence, "elite_members_observed", "Evidence")
    if cohort != ELITE_COHORT_SIZE or observed != ELITE_COHORT_SIZE:
        raise PredictionConfigurationError(
            "Operational elite evidence requires exactly 100 cohort members and "
            f"100 observed members; found cohort={cohort!r}, observed={observed!r}."
        )
    missing_picks = evidence.attrs.get("elite_members_missing_picks")
    unmapped = evidence.attrs.get("unmapped_picked_elements")
    if missing_picks != 0 or unmapped != ():
        raise PredictionConfigurationError(
            "Operational elite evidence requires no missing member picks and no unmapped "
            f"players; found missing={missing_picks!r}, unmapped={unmapped!r}."
        )
    observed_flags = evidence["elite_evidence_observed"]
    if bool(observed_flags.isna().any()) or not bool(observed_flags.astype("boolean").all()):
        raise PredictionConfigurationError(
            "Every player row must carry observed elite evidence for the operational policy."
        )

    projection_ids = set(projection["player_id"].tolist())
    evidence_ids = set(evidence["player_id"].tolist())
    missing_ids = projection_ids - evidence_ids
    extra_ids = evidence_ids - projection_ids

    joined = projection.copy(deep=True).merge(
        evidence.loc[
            :,
            ["player_id", "elite_start_count_lag1", "elite_start_share_lag1"],
        ],
        on="player_id",
        how="left",
        validate="one_to_one",
    )
    evidence_counts = pd.to_numeric(evidence["elite_start_count_lag1"], errors="coerce")
    evidence_shares = pd.to_numeric(evidence["elite_start_share_lag1"], errors="coerce")
    if bool(evidence_counts.isna().any()) or bool(evidence_shares.isna().any()):
        raise PredictionConfigurationError(
            "Observed Top-100 count and share values cannot be missing."
        )
    if bool((evidence_counts.mod(1.0) != 0.0).any()) or not bool(
        evidence_counts.between(0, 100).all()
    ):
        raise PredictionConfigurationError("Top-100 XI counts must be integers within [0, 100].")
    expected_xi_selections = ELITE_XI_SIZE * ELITE_COHORT_SIZE
    if int(evidence_counts.sum()) != expected_xi_selections:
        raise PredictionConfigurationError(
            "Top-100 XI counts must sum to 11 selections per observed member; "
            f"expected {expected_xi_selections}, found {int(evidence_counts.sum())}."
        )
    evidence_support = evidence_counts.astype("float64").div(float(ELITE_COHORT_SIZE))
    disagreement = evidence_shares.astype("float64").sub(evidence_support).abs().gt(1e-12)
    if bool(disagreement.any()):
        raise PredictionConfigurationError(
            "Top-100 XI shares must equal count divided by observed members."
        )

    counts = pd.to_numeric(joined["elite_start_count_lag1"], errors="coerce")
    support = counts.fillna(0.0).astype("float64").div(float(ELITE_COHORT_SIZE))

    points = pd.to_numeric(joined["expected_points"], errors="coerce").astype("float64")
    if bool(points.isna().any()) or not bool(points.map(math.isfinite).all()):
        raise PredictionConfigurationError("Projected points must be finite and present.")
    if bool(points.lt(0.0).any()):
        raise PredictionConfigurationError("Projected points must be non-negative.")

    multiplier = 1.0 + MAXIMUM_RELATIVE_UPLIFT * support
    adjusted = points.mul(multiplier)
    if not bool(adjusted.map(math.isfinite).all()) or bool(adjusted.lt(0.0).any()):
        raise PredictionConfigurationError("Elite-adjusted points must be finite and non-negative.")

    output = projection.copy(deep=True)
    by_id = pd.Series(adjusted.to_numpy(), index=joined["player_id"].tolist())
    output["expected_points"] = [float(by_id.loc[player]) for player in output["player_id"]]
    delta = (
        output["expected_points"]
        .astype("float64")
        .sub(projection["expected_points"].astype("float64").to_numpy())
    )
    diagnostics = MappingProxyType(
        {
            "elite_evidence_policy_version": ELITE_EVIDENCE_POLICY_VERSION,
            "elite_evidence_cohort_size": ELITE_COHORT_SIZE,
            "elite_evidence_members_observed": ELITE_COHORT_SIZE,
            "elite_evidence_maximum_relative_uplift": MAXIMUM_RELATIVE_UPLIFT,
            "elite_evidence_players": len(output),
            "elite_evidence_players_matched": len(output) - len(missing_ids),
            "elite_evidence_players_missing": len(missing_ids),
            "elite_evidence_players_not_on_roster": len(extra_ids),
            "elite_evidence_players_uplifted": int(support.gt(0.0).sum()),
            "elite_evidence_mean_points_delta": float(delta.mean()),
            "elite_evidence_max_points_delta": float(delta.max()),
            "elite_evidence_table_sha256": str(evidence.attrs.get("table_sha256", "")),
        }
    )
    return EliteEvidenceAdjustment(table=output, diagnostics=diagnostics)

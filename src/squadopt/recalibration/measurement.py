"""Measure matched residual regimes after attaching pre-deadline fixture context."""

import hashlib
import json
import math
from numbers import Integral
from typing import Final

import numpy as np
import pandas as pd

from squadopt.data.errors import DataError
from squadopt.data.schema import FIXTURE_SCHEMA_VERSION, POSITIONS
from squadopt.features.config import FeatureConfigurationError
from squadopt.features.fixtures import attach_fixture_features
from squadopt.recalibration.models import (
    FIXTURE_GROUPS,
    RESIDUAL_COLUMNS,
    CalendarRecalibrationResult,
    FixtureResidualComparison,
    RecalibrationConfig,
    RecalibrationValidationError,
    ResidualMetrics,
)

_PAIR_KEY: Final = ("fold_id", "player_id")
_INVARIANT_COLUMNS: Final = ("season", "gameweek", "team_id", "position")


def _identifier_kind(values: list[object], column: str) -> str:
    kinds: set[str] = set()
    for value in values:
        if isinstance(value, bool):
            raise RecalibrationValidationError(
                f"Residual column {column!r} must contain string or integer identifiers."
            )
        if isinstance(value, Integral):
            kinds.add("integer")
        elif isinstance(value, str) and value.strip():
            kinds.add("string")
        else:
            raise RecalibrationValidationError(
                f"Residual column {column!r} must contain string or integer identifiers."
            )
    if len(kinds) != 1:
        raise RecalibrationValidationError(
            f"Residual column {column!r} must use one consistent identifier type."
        )
    return next(iter(kinds))


def _numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    if any(isinstance(value, bool) for value in frame[column].tolist()):
        raise RecalibrationValidationError(
            f"Residual column {column!r} must contain finite numeric values."
        )
    try:
        values = pd.to_numeric(frame[column], errors="raise").astype("float64")
    except (TypeError, ValueError) as error:
        raise RecalibrationValidationError(
            f"Residual column {column!r} must contain finite numeric values."
        ) from error
    if not bool(np.isfinite(values.to_numpy()).all()):
        raise RecalibrationValidationError(
            f"Residual column {column!r} must contain finite numeric values."
        )
    return values


def validate_residual_regimes(
    residuals: object,
    config: RecalibrationConfig,
) -> pd.DataFrame:
    """Return a validated, matched copy of the two residual regimes."""

    if not isinstance(residuals, pd.DataFrame):
        raise RecalibrationValidationError("residuals must be a pandas DataFrame.")
    duplicated_columns = residuals.columns[residuals.columns.duplicated()].tolist()
    if duplicated_columns:
        raise RecalibrationValidationError(
            f"Residual table contains duplicate columns: {duplicated_columns!r}."
        )
    missing = [column for column in RESIDUAL_COLUMNS if column not in residuals.columns]
    if missing:
        raise RecalibrationValidationError(f"Residual table is missing columns: {missing!r}.")
    frame = residuals.loc[:, list(RESIDUAL_COLUMNS)].copy(deep=True)
    if frame.empty:
        raise RecalibrationValidationError("Residual table must contain at least one row.")
    missing_values = [column for column in frame if bool(frame[column].isna().any())]
    if missing_values:
        raise RecalibrationValidationError(
            f"Residual table contains missing values in: {missing_values!r}."
        )

    candidates = {str(value).strip() for value in frame["candidate"].tolist()}
    expected_candidates = {config.reference_candidate, config.candidate}
    if candidates != expected_candidates:
        raise RecalibrationValidationError(
            f"Residual table must contain exactly candidates {sorted(expected_candidates)!r}; "
            f"got {sorted(candidates)!r}."
        )
    frame["candidate"] = frame["candidate"].astype("string").str.strip()

    for column in ("fold_id", "season", "team_id"):
        invalid = [
            value for value in frame[column] if not isinstance(value, str) or not value.strip()
        ]
        if invalid:
            raise RecalibrationValidationError(
                f"Residual column {column!r} must contain non-empty strings."
            )
        frame[column] = frame[column].astype("string").str.strip()
    _identifier_kind(frame["player_id"].tolist(), "player_id")

    gameweeks: list[int] = []
    for value in frame["gameweek"]:
        if isinstance(value, bool) or not isinstance(value, Integral) or int(value) < 1:
            raise RecalibrationValidationError(
                "Residual column 'gameweek' must contain positive integers."
            )
        gameweeks.append(int(value))
    frame["gameweek"] = pd.Series(gameweeks, index=frame.index, dtype="int64")

    expected_fold_ids = [
        f"{season}-gw{gameweek:02d}"
        for season, gameweek in zip(frame["season"], frame["gameweek"], strict=True)
    ]
    if expected_fold_ids != frame["fold_id"].tolist():
        raise RecalibrationValidationError(
            "Residual fold_id must equal '<season>-gwNN' for every row."
        )

    invalid_positions = sorted(
        {str(value) for value in frame["position"] if value not in POSITIONS}
    )
    if invalid_positions:
        raise RecalibrationValidationError(
            f"Residual positions must be in {list(POSITIONS)!r}; got {invalid_positions!r}."
        )
    frame["position"] = frame["position"].astype("string")

    for column in ("predicted_points", "realized_points", "residual"):
        frame[column] = _numeric(frame, column)
    if bool((frame["predicted_points"] < 0.0).any()):
        raise RecalibrationValidationError("predicted_points must be non-negative.")
    calculated = frame["realized_points"] - frame["predicted_points"]
    if not bool(np.allclose(calculated, frame["residual"], rtol=1e-10, atol=1e-10)):
        raise RecalibrationValidationError(
            "residual must equal realized_points minus predicted_points."
        )

    duplicate_rows = frame.duplicated(subset=["candidate", *_PAIR_KEY], keep=False)
    if bool(duplicate_rows.any()):
        raise RecalibrationValidationError(
            "Residual table must contain at most one row per candidate, fold_id and player_id."
        )

    reference = frame.loc[frame["candidate"] == config.reference_candidate]
    candidate = frame.loc[frame["candidate"] == config.candidate]
    paired = reference.merge(
        candidate,
        on=list(_PAIR_KEY),
        how="outer",
        suffixes=("_reference", "_candidate"),
        indicator=True,
        validate="one_to_one",
    )
    unmatched = paired.loc[paired["_merge"] != "both", list(_PAIR_KEY)]
    if not unmatched.empty:
        raise RecalibrationValidationError(
            "Residual regimes must contain identical fold/player rows; unmatched examples: "
            f"{unmatched.head(10).to_dict(orient='records')!r}."
        )
    for column in _INVARIANT_COLUMNS:
        if not bool((paired[f"{column}_reference"] == paired[f"{column}_candidate"]).all()):
            raise RecalibrationValidationError(
                f"Residual regimes disagree on invariant column {column!r}."
            )
    if not bool(
        np.allclose(
            paired["realized_points_reference"],
            paired["realized_points_candidate"],
            rtol=1e-10,
            atol=1e-10,
        )
    ):
        raise RecalibrationValidationError(
            "Residual regimes must score the same realized_points for each paired row."
        )

    return frame.sort_values(
        ["candidate", "season", "gameweek", "player_id"], kind="stable"
    ).reset_index(drop=True)


def _fixture_group(count: int) -> str:
    if count == 0:
        return "blank"
    if count == 1:
        return "single"
    return "double_plus"


def _metrics(values: pd.Series) -> ResidualMetrics:
    residuals = values.to_numpy(dtype="float64")
    return ResidualMetrics(
        observations=len(residuals),
        mean_residual=float(residuals.mean()),
        residual_stddev=float(residuals.std(ddof=0)),
        mean_absolute_error=float(np.abs(residuals).mean()),
        root_mean_squared_error=float(math.sqrt(float(np.square(residuals).mean()))),
    )


def _comparison(
    paired: pd.DataFrame,
    fixture_group: str,
) -> FixtureResidualComparison:
    reference = _metrics(paired["residual_reference"])
    candidate = _metrics(paired["residual_candidate"])
    return FixtureResidualComparison(
        fixture_group=fixture_group,
        observations=reference.observations,
        reference=reference,
        candidate=candidate,
        mean_residual_delta=candidate.mean_residual - reference.mean_residual,
        residual_stddev_delta=candidate.residual_stddev - reference.residual_stddev,
        mean_absolute_error_delta=(candidate.mean_absolute_error - reference.mean_absolute_error),
        root_mean_squared_error_delta=(
            candidate.root_mean_squared_error - reference.root_mean_squared_error
        ),
    )


def _fingerprint(frame: pd.DataFrame, config: RecalibrationConfig) -> str:
    payload = {
        "contract_version": config.contract_version,
        "reference_candidate": config.reference_candidate,
        "candidate": config.candidate,
        "rows": frame.loc[:, [*RESIDUAL_COLUMNS, "fixture_count", "fixture_group"]]
        .sort_values(["candidate", "season", "gameweek", "player_id"], kind="stable")
        .to_dict(orient="records"),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _regime_fingerprint(frame: pd.DataFrame, candidate: str) -> str:
    rows = (
        frame.loc[frame["candidate"] == candidate, list(RESIDUAL_COLUMNS)]
        .sort_values(["season", "gameweek", "player_id"], kind="stable")
        .to_dict(orient="records")
    )
    encoded = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def measure_calendar_recalibration(
    residuals: pd.DataFrame,
    fixtures: pd.DataFrame,
    team_codes: pd.DataFrame,
    config: RecalibrationConfig | None = None,
) -> CalendarRecalibrationResult:
    """Compare matched residual regimes overall and by known fixture count."""

    settings = RecalibrationConfig() if config is None else config
    if not isinstance(settings, RecalibrationConfig):
        raise RecalibrationValidationError("config must be a RecalibrationConfig.")
    validated = validate_residual_regimes(residuals, settings)
    try:
        enriched = attach_fixture_features(validated, fixtures, team_codes)
    except (DataError, FeatureConfigurationError) as error:
        raise RecalibrationValidationError(
            f"Fixture context could not be attached to residual regimes: {error}"
        ) from error
    enriched["fixture_group"] = pd.Series(
        [_fixture_group(int(value)) for value in enriched["fixture_count"]],
        index=enriched.index,
        dtype="string",
    )

    reference = enriched.loc[enriched["candidate"] == settings.reference_candidate]
    candidate = enriched.loc[enriched["candidate"] == settings.candidate]
    paired = reference.merge(
        candidate,
        on=list(_PAIR_KEY),
        suffixes=("_reference", "_candidate"),
        validate="one_to_one",
    )
    if not bool((paired["fixture_group_reference"] == paired["fixture_group_candidate"]).all()):
        raise RecalibrationValidationError(
            "Paired residual regimes received different fixture-count groups."
        )

    comparisons = [_comparison(paired, "overall")]
    for fixture_group in FIXTURE_GROUPS:
        group = paired.loc[paired["fixture_group_reference"] == fixture_group]
        if not group.empty:
            comparisons.append(_comparison(group, fixture_group))

    distribution = {
        group: int((reference["fixture_group"] == group).sum()) for group in FIXTURE_GROUPS
    }
    return CalendarRecalibrationResult(
        config=settings,
        comparisons=tuple(comparisons),
        residuals_with_fixture_context=enriched,
        measurement_fingerprint=_fingerprint(enriched, settings),
        diagnostics={
            "paired_rows": len(reference),
            "seasons": tuple(sorted(reference["season"].unique().tolist())),
            "folds": int(reference["fold_id"].nunique()),
            "fixture_group_counts": distribution,
            "fixture_contract_version": FIXTURE_SCHEMA_VERSION,
            "residual_fingerprints": {
                settings.reference_candidate: _regime_fingerprint(
                    enriched, settings.reference_candidate
                ),
                settings.candidate: _regime_fingerprint(enriched, settings.candidate),
            },
            "measurement_scope": "residual_regime_only",
            "conformal_recalibrated": False,
            "player_adaptive_scales_refit": False,
            "scenario_decomposition_refit": False,
        },
    )

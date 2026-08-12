"""Versioned realized-points scoring for frozen squad decisions."""

import math
from decimal import Decimal, InvalidOperation
from numbers import Integral, Real

import pandas as pd

from squadopt.evaluation.models import EvaluationValidationError, ScoringPolicy
from squadopt.optimization import OptimizationResult

REALIZED_POINTS_COLUMNS: tuple[str, str] = ("player_id", "total_points")
MAX_ERROR_EXAMPLES = 10


def _validate_realized_points(realized_points: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(realized_points, pd.DataFrame):
        raise EvaluationValidationError("realized_points must be a pandas DataFrame.")

    duplicate_columns = realized_points.columns[realized_points.columns.duplicated()].tolist()
    if duplicate_columns:
        raise EvaluationValidationError(
            f"Duplicate realized-points columns are not allowed: {duplicate_columns!r}."
        )

    missing_columns = [
        column for column in REALIZED_POINTS_COLUMNS if column not in realized_points.columns
    ]
    if missing_columns:
        raise EvaluationValidationError(
            f"Realized points are missing required columns: {missing_columns!r}."
        )

    validated = realized_points.loc[:, list(REALIZED_POINTS_COLUMNS)].copy(deep=True)
    if validated.empty:
        raise EvaluationValidationError("Realized points must contain at least one player row.")
    columns_with_missing = [
        column for column in REALIZED_POINTS_COLUMNS if bool(validated[column].isna().any())
    ]
    if columns_with_missing:
        raise EvaluationValidationError(
            f"Realized-points columns contain missing values: {columns_with_missing!r}."
        )

    invalid_ids: list[object] = []
    id_kinds: set[str] = set()
    for value in validated["player_id"].tolist():
        if isinstance(value, bool):
            invalid_ids.append(value)
        elif isinstance(value, Integral):
            id_kinds.add("integer")
        elif isinstance(value, str) and value.strip():
            id_kinds.add("string")
        else:
            invalid_ids.append(value)
    if invalid_ids:
        raise EvaluationValidationError(
            "Realized player_id values must be non-empty strings or integers; "
            f"invalid examples: {invalid_ids[:MAX_ERROR_EXAMPLES]!r}."
        )
    if len(id_kinds) > 1:
        raise EvaluationValidationError(
            f"Realized player_id must use one consistent ID type; found {sorted(id_kinds)!r}."
        )

    duplicate_ids = (
        validated.loc[validated["player_id"].duplicated(keep=False), "player_id"]
        .drop_duplicates()
        .tolist()
    )
    if duplicate_ids:
        raise EvaluationValidationError(
            f"Realized points contain duplicate player_id values: "
            f"{duplicate_ids[:MAX_ERROR_EXAMPLES]!r}."
        )

    invalid_points: list[object] = []
    converted_points: list[Decimal] = []
    for value in validated["total_points"].tolist():
        if isinstance(value, bool) or not isinstance(value, (Real, Decimal)):
            invalid_points.append(value)
            continue
        try:
            number = Decimal(str(value))
        except (InvalidOperation, ValueError, OverflowError):
            invalid_points.append(value)
            continue
        if not number.is_finite():
            invalid_points.append(value)
            continue
        converted_points.append(number)
    if invalid_points:
        raise EvaluationValidationError(
            "Realized total_points values must be finite numbers; "
            f"invalid examples: {invalid_points[:MAX_ERROR_EXAMPLES]!r}."
        )

    validated = validated.assign(
        total_points=pd.Series(converted_points, index=validated.index, dtype="object")
    )

    return validated


def score_realized_squad_points(
    optimization_result: OptimizationResult,
    realized_points: pd.DataFrame,
    *,
    policy: ScoringPolicy = ScoringPolicy.STARTING_XI_CAPTAIN_V1,
) -> float:
    """Score a feasible frozen decision from later realized player points.

    Version 1 sums the starting XI and adds the captain's points a second time.
    Bench points and automatic substitutions are intentionally excluded.
    """

    if not isinstance(optimization_result, OptimizationResult):
        raise EvaluationValidationError(
            "optimization_result must be an OptimizationResult instance."
        )
    if not isinstance(policy, ScoringPolicy):
        raise EvaluationValidationError("policy must be a ScoringPolicy value.")
    if policy is not ScoringPolicy.STARTING_XI_CAPTAIN_V1:
        raise EvaluationValidationError(f"Unsupported scoring policy: {policy!r}.")
    if not optimization_result.has_solution:
        raise EvaluationValidationError(
            "A realized score requires an OPTIMAL or FEASIBLE optimization result."
        )
    if optimization_result.captain is None:
        raise EvaluationValidationError("A feasible optimization result must contain a captain.")

    validated = _validate_realized_points(realized_points)
    points_by_player = {
        player_id: Decimal(str(total_points))
        for player_id, total_points in validated.itertuples(index=False, name=None)
    }

    starter_ids = optimization_result.starting_xi["player_id"].tolist()
    captain_id = optimization_result.captain["player_id"]
    required_ids = list(dict.fromkeys([*starter_ids, captain_id]))
    missing_ids = [player_id for player_id in required_ids if player_id not in points_by_player]
    if missing_ids:
        raise EvaluationValidationError(
            "Realized points do not cover every selected starter and captain; "
            f"missing player_id values: {missing_ids[:MAX_ERROR_EXAMPLES]!r}."
        )

    total = sum((points_by_player[player_id] for player_id in starter_ids), start=Decimal(0))
    total += points_by_player[captain_id]
    score = float(total)
    if not math.isfinite(score):
        raise EvaluationValidationError(
            "Realized squad score exceeds the supported finite float range."
        )
    return score

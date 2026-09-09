"""Versioned realized-points scoring for frozen squad decisions."""

from __future__ import annotations

import math
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from numbers import Integral, Real
from typing import Any

import pandas as pd

from squadopt.evaluation.models import (
    EvaluationValidationError,
    FrozenSquadDecision,
    RealizedSquadScore,
    ScoringPolicy,
)
from squadopt.optimization import OptimizationResult
from squadopt.optimization.config import POSITIONS, Position

REALIZED_POINTS_COLUMNS: tuple[str, str] = ("player_id", "total_points")
MAX_ERROR_EXAMPLES = 10
OPTIMIZER_COMPLETION_POLICY = "optimizer_projection_order_v1"
FPL_SQUAD_POSITION_LIMITS: dict[str, int] = {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}
FPL_STARTING_POSITION_MIN: dict[str, int] = {"GK": 1, "DEF": 3, "MID": 2, "FWD": 1}
FPL_STARTING_POSITION_MAX: dict[str, int] = {"GK": 1, "DEF": 5, "MID": 5, "FWD": 3}


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


def _identifier_sort_key(value: object) -> tuple[int, str]:
    if isinstance(value, Integral) and not isinstance(value, bool):
        return (0, f"{int(value):+030d}")
    return (1, str(value))


def _validate_frozen_decision(decision: FrozenSquadDecision) -> pd.DataFrame:
    if not isinstance(decision, FrozenSquadDecision):
        raise EvaluationValidationError("decision must be a FrozenSquadDecision instance.")

    frame = decision.squad.copy(deep=True)
    duplicate_columns = frame.columns[frame.columns.duplicated()].tolist()
    if duplicate_columns:
        raise EvaluationValidationError(
            f"Duplicate frozen-squad columns are not allowed: {duplicate_columns!r}."
        )
    missing = [column for column in ("player_id", "position") if column not in frame.columns]
    if missing:
        raise EvaluationValidationError(f"Frozen squad is missing required columns: {missing!r}.")
    if len(frame) != 15:
        raise EvaluationValidationError("A frozen FPL squad must contain exactly 15 players.")
    if bool(frame[["player_id", "position"]].isna().any().any()):
        raise EvaluationValidationError("Frozen squad player_id and position cannot be missing.")
    if bool(frame["player_id"].duplicated().any()):
        raise EvaluationValidationError("Frozen squad player_id values must be unique.")

    squad_ids = frame["player_id"].tolist()
    kinds = {
        "integer"
        if isinstance(value, Integral) and not isinstance(value, bool)
        else "string"
        if isinstance(value, str) and value.strip()
        else "invalid"
        for value in squad_ids
    }
    if "invalid" in kinds or len(kinds) != 1:
        raise EvaluationValidationError(
            "Frozen squad player_id values must use one consistent non-empty "
            "string or integer type."
        )

    positions = frame["position"].astype(str)
    invalid_positions = sorted(set(positions) - set(POSITIONS))
    if invalid_positions:
        raise EvaluationValidationError(
            f"Frozen squad contains invalid positions: {invalid_positions!r}."
        )
    squad_counts = positions.value_counts().to_dict()
    if any(
        int(squad_counts.get(position, 0)) != count
        for position, count in FPL_SQUAD_POSITION_LIMITS.items()
    ):
        raise EvaluationValidationError(
            "Frozen squad must use the 2 GK / 5 DEF / 5 MID / 3 FWD position quotas."
        )

    starters = decision.starting_xi
    bench = decision.bench
    if len(starters) != 11 or len(set(starters)) != 11:
        raise EvaluationValidationError("Frozen starting_xi must contain 11 distinct players.")
    if len(bench) != 4 or len(set(bench)) != 4:
        raise EvaluationValidationError("Frozen bench must contain four distinct ordered players.")
    if set(starters) | set(bench) != set(squad_ids) or set(starters) & set(bench):
        raise EvaluationValidationError(
            "Frozen starting_xi and bench must partition the 15-player squad."
        )
    if decision.captain_id not in starters:
        raise EvaluationValidationError("Frozen captain must be in the starting XI.")
    if decision.vice_captain_id not in squad_ids:
        raise EvaluationValidationError("Frozen vice-captain must be in the squad.")
    if decision.vice_captain_id == decision.captain_id:
        raise EvaluationValidationError("Frozen captain and vice-captain must differ.")

    position_by_id = dict(zip(squad_ids, positions.tolist(), strict=True))
    starter_counts = {position: 0 for position in POSITIONS}
    for player_id in starters:
        starter_counts[position_by_id[player_id]] += 1
    if any(
        not FPL_STARTING_POSITION_MIN[position]
        <= starter_counts[position]
        <= FPL_STARTING_POSITION_MAX[position]
        for position in POSITIONS
    ):
        raise EvaluationValidationError("Frozen starting_xi does not use a legal FPL formation.")
    if sum(position_by_id[player_id] == "GK" for player_id in bench) != 1:
        raise EvaluationValidationError("Frozen bench must contain exactly one goalkeeper.")
    return frame


def _validate_realized_outcomes(realized_points: pd.DataFrame) -> pd.DataFrame:
    validated_points = _validate_realized_points(realized_points)
    if "minutes" not in realized_points.columns:
        raise EvaluationValidationError("Realized outcomes are missing required column: 'minutes'.")
    minutes = realized_points.loc[:, ["player_id", "minutes"]].copy(deep=True)
    invalid_minutes = [
        value
        for value in minutes["minutes"].tolist()
        if isinstance(value, bool) or not isinstance(value, Integral) or int(value) < 0
    ]
    if invalid_minutes or bool(minutes["minutes"].isna().any()):
        raise EvaluationValidationError(
            "Realized minutes values must be non-negative integers; "
            f"invalid examples: {invalid_minutes[:MAX_ERROR_EXAMPLES]!r}."
        )
    joined = validated_points.merge(minutes, on="player_id", how="left", validate="one_to_one")
    joined["minutes"] = joined["minutes"].astype(int)
    return joined


def complete_optimization_decision(
    optimization_result: OptimizationResult,
) -> FrozenSquadDecision:
    """Complete an old optimizer result without consulting realized outcomes."""

    if not isinstance(optimization_result, OptimizationResult):
        raise EvaluationValidationError(
            "optimization_result must be an OptimizationResult instance."
        )
    if not optimization_result.has_solution or optimization_result.captain is None:
        raise EvaluationValidationError(
            "A frozen decision requires an OPTIMAL or FEASIBLE result with a captain."
        )
    squad = optimization_result.selected_squad.copy(deep=True)
    required = ["player_id", "position", "expected_points"]
    missing = [column for column in required if column not in squad.columns]
    if missing:
        raise EvaluationValidationError(
            f"Decision-time squad is missing completion columns: {missing!r}."
        )
    if bool(squad[required].isna().any().any()):
        raise EvaluationValidationError("Decision-time completion columns cannot be missing.")

    starters = tuple(optimization_result.starting_xi["player_id"].tolist())
    captain_id = optimization_result.captain["player_id"]
    bench_frame = optimization_result.bench.copy(deep=True)
    bench_goalkeepers = bench_frame.loc[bench_frame["position"] == "GK"]
    bench_outfield = bench_frame.loc[bench_frame["position"] != "GK"]
    if len(bench_goalkeepers) != 1:
        raise EvaluationValidationError(
            "A completed optimizer bench requires exactly one goalkeeper."
        )

    def ranking(row: pd.Series[Any]) -> tuple[Decimal, tuple[int, str]]:
        try:
            points = Decimal(str(row["expected_points"]))
        except (InvalidOperation, ValueError, OverflowError) as error:
            raise EvaluationValidationError(
                "Decision-time expected_points must be finite numbers."
            ) from error
        if not points.is_finite():
            raise EvaluationValidationError("Decision-time expected_points must be finite numbers.")
        return (-points, _identifier_sort_key(row["player_id"]))

    outfield_records = [row for _, row in bench_outfield.iterrows()]
    outfield_records.sort(key=ranking)
    bench = (
        bench_goalkeepers.iloc[0]["player_id"],
        *(row["player_id"] for row in outfield_records),
    )

    starter_frame = squad.loc[squad["player_id"].isin(starters)]
    vice_candidates = [row for _, row in starter_frame.iterrows() if row["player_id"] != captain_id]
    vice_candidates.sort(key=ranking)
    if not vice_candidates:
        raise EvaluationValidationError("A completed decision requires a vice-captain candidate.")
    return FrozenSquadDecision(
        squad=squad,
        starting_xi=starters,
        bench=bench,
        captain_id=captain_id,
        vice_captain_id=vice_candidates[0]["player_id"],
        completion_policy=OPTIMIZER_COMPLETION_POLICY,
    )


def _formation_is_legal(counts: Mapping[Position, int]) -> bool:
    return all(
        FPL_STARTING_POSITION_MIN[position]
        <= counts[position]
        <= FPL_STARTING_POSITION_MAX[position]
        for position in POSITIONS
    )


def score_frozen_squad_decision(
    decision: FrozenSquadDecision,
    realized_points: pd.DataFrame,
) -> RealizedSquadScore:
    """Apply normal-week autosubs and captain fallback to one frozen decision."""

    squad = _validate_frozen_decision(decision)
    outcomes = _validate_realized_outcomes(realized_points)
    points = {
        player_id: Decimal(str(total_points))
        for player_id, total_points in outcomes[["player_id", "total_points"]].itertuples(
            index=False, name=None
        )
    }
    minutes = dict(outcomes[["player_id", "minutes"]].itertuples(index=False, name=None))
    squad_ids = squad["player_id"].tolist()
    missing = [
        player_id for player_id in squad_ids if player_id not in points or player_id not in minutes
    ]
    if missing:
        raise EvaluationValidationError(
            "Realized outcomes do not cover every frozen squad player; "
            f"missing player_id values: {missing[:MAX_ERROR_EXAMPLES]!r}."
        )

    position_by_id = dict(
        squad.loc[:, ["player_id", "position"]].itertuples(index=False, name=None)
    )
    final_slots = list(decision.starting_xi)
    autosubs: list[tuple[object, object]] = []

    starting_goalkeeper = next(
        player_id for player_id in decision.starting_xi if position_by_id[player_id] == "GK"
    )
    bench_goalkeeper = next(
        player_id for player_id in decision.bench if position_by_id[player_id] == "GK"
    )
    if minutes[starting_goalkeeper] == 0 and minutes[bench_goalkeeper] > 0:
        slot = final_slots.index(starting_goalkeeper)
        final_slots[slot] = bench_goalkeeper
        autosubs.append((starting_goalkeeper, bench_goalkeeper))

    nominal_counts = {position: 0 for position in POSITIONS}
    for player_id in decision.starting_xi:
        nominal_counts[position_by_id[player_id]] += 1
    missing_outfield = [
        player_id
        for player_id in decision.starting_xi
        if position_by_id[player_id] != "GK" and minutes[player_id] == 0
    ]
    for substitute in decision.bench:
        if position_by_id[substitute] == "GK" or minutes[substitute] == 0:
            continue
        for outgoing in tuple(missing_outfield):
            candidate_counts = nominal_counts.copy()
            candidate_counts[position_by_id[outgoing]] -= 1
            candidate_counts[position_by_id[substitute]] += 1
            if not _formation_is_legal(candidate_counts):
                continue
            slot = final_slots.index(outgoing)
            final_slots[slot] = substitute
            nominal_counts = candidate_counts
            missing_outfield.remove(outgoing)
            autosubs.append((outgoing, substitute))
            break

    final_xi = tuple(player_id for player_id in final_slots if minutes[player_id] > 0)
    base_score = sum((points[player_id] for player_id in final_xi), start=Decimal(0))
    bonus_player: object | None = None
    bonus = Decimal(0)
    if minutes[decision.captain_id] > 0:
        bonus_player = decision.captain_id
        bonus = points[decision.captain_id]
    elif decision.vice_captain_id in final_xi and minutes[decision.vice_captain_id] > 0:
        bonus_player = decision.vice_captain_id
        bonus = points[decision.vice_captain_id]

    total = base_score + bonus
    autosub_points = sum((points[incoming] for _, incoming in autosubs), start=Decimal(0))
    score = float(total)
    if not math.isfinite(score):
        raise EvaluationValidationError(
            "Realized squad score exceeds the supported finite float range."
        )
    return RealizedSquadScore(
        policy=ScoringPolicy.OFFICIAL_AUTOSUB_CAPTAIN_V2,
        total_points=score,
        final_xi=final_xi,
        autosubs=tuple(autosubs),
        captain_bonus_player_id=bonus_player,
        captain_bonus_points=float(bonus),
        autosub_points=float(autosub_points),
    )


def score_realized_squad_points(
    optimization_result: OptimizationResult,
    realized_points: pd.DataFrame,
    *,
    policy: ScoringPolicy = ScoringPolicy.STARTING_XI_CAPTAIN_V1,
) -> float:
    """Score a feasible frozen decision from later realized player points.

    Version 1 sums the starting XI and adds the captain's points a second time.
    Version 2 completes the old optimizer decision from decision-time projections,
    then applies normal-week automatic substitutions and vice-captain fallback.
    """

    if not isinstance(optimization_result, OptimizationResult):
        raise EvaluationValidationError(
            "optimization_result must be an OptimizationResult instance."
        )
    if not isinstance(policy, ScoringPolicy):
        raise EvaluationValidationError("policy must be a ScoringPolicy value.")
    if not optimization_result.has_solution:
        raise EvaluationValidationError(
            "A realized score requires an OPTIMAL or FEASIBLE optimization result."
        )
    if optimization_result.captain is None:
        raise EvaluationValidationError("A feasible optimization result must contain a captain.")

    if policy is ScoringPolicy.OFFICIAL_AUTOSUB_CAPTAIN_V2:
        decision = complete_optimization_decision(optimization_result)
        return score_frozen_squad_decision(decision, realized_points).total_points
    if policy is not ScoringPolicy.STARTING_XI_CAPTAIN_V1:
        raise EvaluationValidationError(f"Unsupported scoring policy: {policy!r}.")

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

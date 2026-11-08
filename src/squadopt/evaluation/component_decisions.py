"""Decision-level evaluation for a verified Phase C component handoff."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from statistics import fmean, median
from types import MappingProxyType
from typing import Any

import pandas as pd

from squadopt.evaluation.component_handoff import HANDOFF_KEY, PhaseCComponentHandoff
from squadopt.evaluation.evaluator import evaluate_prepared_folds
from squadopt.evaluation.models import (
    EvaluationConfig,
    EvaluationFold,
    EvaluationResult,
    EvaluationValidationError,
    FoldEvaluationResult,
    FrozenSquadDecision,
    ScoringPolicy,
)
from squadopt.evaluation.scoring import (
    complete_optimization_decision,
    score_frozen_squad_decision,
)


@dataclass(frozen=True, slots=True)
class PhaseCDecisionDiagnostics:
    """Paired official-scoring diagnostics without a promotion verdict."""

    attempted_folds: int
    comparable_folds: int
    candidate_wins: int
    ties: int
    candidate_losses: int
    mean_difference: float | None
    median_difference: float | None
    season_mean_differences: Mapping[str, float]
    candidate_zero_minute_starters: int
    control_zero_minute_starters: int
    candidate_autosub_points: float
    control_autosub_points: float
    candidate_vice_captain_recoveries: int
    control_vice_captain_recoveries: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "season_mean_differences",
            MappingProxyType(dict(self.season_mean_differences)),
        )


@dataclass(frozen=True, slots=True)
class PhaseCDecisionComparison:
    """Control and component-base decisions scored on identical folds.

    ``decisions`` is empty unless the caller asked for the solved squads: then it maps each
    fold id to the two arms' squads, lineups, captaincy, objective, bound, solver work and
    both scores (official rule, and the same rule with card participation ignored), so a
    reader can measure squad overlap and the share of a paired difference that is the
    scoring convention rather than the forecast.
    """

    control: EvaluationResult
    component_base: EvaluationResult
    diagnostics: PhaseCDecisionDiagnostics
    decisions: Mapping[str, Mapping[str, object]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "decisions", MappingProxyType(dict(self.decisions)))


@dataclass(frozen=True, slots=True)
class _FoldDecisionDetail:
    fold_id: str
    score: float
    zero_minute_starters: int
    autosub_points: float
    vice_recovered: bool
    decision: Mapping[str, object] = field(default_factory=dict)


def _folds(values: Iterable[EvaluationFold]) -> tuple[EvaluationFold, ...]:
    if isinstance(values, str | bytes):
        raise EvaluationValidationError("control_folds must contain EvaluationFold values.")
    try:
        folds = tuple(values)
    except TypeError as error:
        raise EvaluationValidationError("control_folds must be iterable.") from error
    if not folds or any(not isinstance(item, EvaluationFold) for item in folds):
        raise EvaluationValidationError(
            "control_folds must contain at least one EvaluationFold value."
        )
    ids = [item.fold_id for item in folds]
    if len(ids) != len(set(ids)):
        raise EvaluationValidationError("control_folds must have unique fold_id values.")
    return folds


def _outcomes(rows: pd.DataFrame, actual: pd.DataFrame, fold_id: str) -> pd.DataFrame:
    """The fold's realized outcomes keyed to the handoff roster.

    ``card_participation`` is carried through when the control fold's outcomes hold it: a
    player booked without a minute counts as having played for the automatic substitution
    under the official rules, and the scorer reads that column. A fold without the column
    scores as before, with every participation read from minutes alone.
    """

    appeared = rows["appearance_target"].eq(1.0)
    if bool(rows["appearance_target"].isna().any()):
        raise EvaluationValidationError(
            "Decision scoring requires an observed appearance target for every player."
        )
    if bool(rows.loc[appeared, ["points_target", "minutes_target"]].isna().any().any()):
        raise EvaluationValidationError(
            "Decision scoring requires points and minutes for every appearance."
        )
    required = ("player_id", "total_points")
    missing = [column for column in required if column not in actual]
    if missing:
        raise EvaluationValidationError(
            f"Control fold {fold_id!r} realized outcomes are missing {missing!r}."
        )
    if bool(actual["player_id"].duplicated().any()) or bool(
        actual[list(required)].isna().any().any()
    ):
        raise EvaluationValidationError(f"Control fold {fold_id!r} has invalid realized outcomes.")
    merged = rows.loc[
        :, ["player_id", "appearance_target", "points_target", "minutes_target"]
    ].merge(actual.loc[:, list(required)], on="player_id", how="left", validate="one_to_one")
    if len(merged) != len(actual) or bool(merged["total_points"].isna().any()):
        raise EvaluationValidationError(
            f"Control fold {fold_id!r} outcomes do not exactly cover the handoff roster."
        )
    appeared = merged["appearance_target"].eq(1.0)
    expected_points = pd.to_numeric(merged.loc[appeared, "points_target"], errors="raise").astype(
        "float64"
    )
    actual_points = pd.to_numeric(merged.loc[appeared, "total_points"], errors="raise").astype(
        "float64"
    )
    if not expected_points.equals(actual_points):
        raise EvaluationValidationError(
            f"Control fold {fold_id!r} changes handoff appeared-player points outcomes."
        )
    minute_values = pd.to_numeric(
        merged["minutes_target"].where(appeared, 0), errors="raise"
    ).astype("float64")
    if bool(minute_values.lt(0.0).any() or minute_values.mod(1.0).ne(0.0).any()):
        raise EvaluationValidationError(
            f"Phase C fold {fold_id!r} realized minutes must be non-negative integers."
        )
    minutes = minute_values.astype("int64")
    if "minutes" in actual:
        actual_minutes = actual.loc[:, ["player_id", "minutes"]]
        numeric_actual_minutes = pd.to_numeric(actual_minutes["minutes"], errors="raise").astype(
            "float64"
        )
        if bool(
            numeric_actual_minutes.isna().any()
            or numeric_actual_minutes.lt(0.0).any()
            or numeric_actual_minutes.mod(1.0).ne(0.0).any()
        ):
            raise EvaluationValidationError(
                f"Control fold {fold_id!r} realized minutes must be non-negative integers."
            )
        actual_minutes = actual_minutes.assign(minutes=numeric_actual_minutes.astype("int64"))
        compared = (
            merged.loc[:, ["player_id"]]
            .assign(minutes=minutes)
            .merge(
                actual_minutes,
                on="player_id",
                suffixes=("_handoff", "_control"),
                validate="one_to_one",
            )
        )
        if not compared["minutes_handoff"].equals(compared["minutes_control"]):
            raise EvaluationValidationError(
                f"Control fold {fold_id!r} changes handoff minutes outcomes."
            )
    outcomes = pd.DataFrame(
        {
            "player_id": merged["player_id"],
            "total_points": merged["total_points"],
            "minutes": minutes,
        }
    )
    if "card_participation" in actual:
        cards = actual.loc[:, ["player_id", "card_participation"]]
        if cards["card_participation"].isna().any() or any(
            type(value) is not bool for value in cards["card_participation"].tolist()
        ):
            raise EvaluationValidationError(
                f"Control fold {fold_id!r} card_participation must contain non-missing booleans."
            )
        outcomes = outcomes.merge(cards, on="player_id", how="left", validate="one_to_one")
        if bool(outcomes["card_participation"].isna().any()):
            raise EvaluationValidationError(
                f"Control fold {fold_id!r} card_participation does not cover the roster."
            )
        outcomes["card_participation"] = outcomes["card_participation"].astype(bool)
    return outcomes


def prepare_phase_c_component_folds(
    handoff: PhaseCComponentHandoff,
    control_folds: Iterable[EvaluationFold],
    *,
    development_contract: str | None = None,
) -> tuple[EvaluationFold, ...]:
    """Fill direct-control rows from exact-key control folds and build candidate folds.

    A handoff read under a development contract is admitted only when the caller names that
    same contract: the frozen v1 evidence path never does, and a development caller cannot
    be handed a v1 artifact in its place.
    """

    if not isinstance(handoff, PhaseCComponentHandoff):
        raise EvaluationValidationError("handoff must be a PhaseCComponentHandoff.")
    if handoff.development_contract != development_contract:
        raise EvaluationValidationError(
            "Phase C handoff contract mismatch: the handoff was read under "
            f"{handoff.development_contract!r} and the caller admits "
            f"{development_contract!r}. Development artifacts are development-only."
        )
    controls = _folds(control_folds)
    handoff_order = handoff.rows["fold_id"].drop_duplicates().tolist()
    if [item.fold_id for item in controls] != handoff_order:
        raise EvaluationValidationError(
            "control_folds must have the same complete order as the Phase C handoff."
        )

    candidate_folds: list[EvaluationFold] = []
    for control in controls:
        rows = handoff.rows.loc[handoff.rows["fold_id"].eq(control.fold_id)].copy(deep=True)
        roster = handoff.roster.loc[
            handoff.roster["fold_id"].eq(control.fold_id),
            [*HANDOFF_KEY, "name", "team_id", "position", "price_tenths"],
        ].copy(deep=True)
        fallback = control.projections.loc[:, ["player_id", "expected_points"]].copy(deep=True)
        if (
            fallback.empty
            or bool(fallback.isna().any().any())
            or bool(fallback["player_id"].duplicated().any())
        ):
            raise EvaluationValidationError(
                f"Control fold {control.fold_id!r} has invalid fallback projections."
            )
        merged = rows.merge(fallback, on="player_id", how="left", validate="one_to_one")
        if bool(merged["expected_points"].isna().any()):
            raise EvaluationValidationError(
                f"Control fold {control.fold_id!r} does not exactly cover the handoff roster."
            )
        if len(merged) != len(fallback):
            raise EvaluationValidationError(
                f"Control fold {control.fold_id!r} contains players outside the handoff roster."
            )
        candidate_points = merged["control_expected_points"].fillna(merged["expected_points"])
        projections = roster.loc[
            :, ["player_id", "name", "team_id", "position", "price_tenths"]
        ].copy(deep=True)
        point_map = dict(zip(merged["player_id"], candidate_points, strict=True))
        projections["expected_points"] = projections["player_id"].map(point_map)
        if bool(projections["expected_points"].isna().any()):
            raise EvaluationValidationError(
                f"Phase C fold {control.fold_id!r} has unresolved expected points."
            )

        realized = _outcomes(rows, control.realized_points, control.fold_id)
        candidate_folds.append(
            EvaluationFold(
                fold_id=control.fold_id,
                projections=projections,
                realized_points=realized,
                metadata={
                    "season": str(rows["season"].iloc[0]),
                    "gameweek": int(rows["target_gameweek"].iloc[0]),
                    "phase_c_table_sha256": handoff.table_sha256,
                    "phase_c_roster_sha256": handoff.roster_sha256,
                    "direct_control_rows": int(rows["control_expected_points"].isna().sum()),
                },
            )
        )
    return tuple(candidate_folds)


def _recorded_decision(
    item: FoldEvaluationResult,
    decision: FrozenSquadDecision,
    fold: EvaluationFold,
    score: float,
) -> dict[str, object]:
    """One arm's solved decision on one fold, with both scoring conventions."""

    result = item.optimization_result
    diagnostics = result.diagnostics
    without_cards = fold.realized_points.assign(card_participation=False)
    ignoring_cards = score_frozen_squad_decision(decision, without_cards).total_points
    return {
        "solver_status": result.solver_status.value,
        "objective_value": _plain(result.objective_value),
        "best_objective_bound": _plain(diagnostics.get("best_objective_bound")),
        "deterministic_time_used": _plain(diagnostics.get("deterministic_time_used")),
        "squad": sorted(_plain(value) for value in result.selected_squad["player_id"].tolist()),
        "starting_xi": [_plain(value) for value in decision.starting_xi],
        "bench_order": [_plain(value) for value in decision.bench],
        "captain_id": _plain(decision.captain_id),
        "vice_captain_id": _plain(decision.vice_captain_id),
        "realized_score": _plain(score),
        "realized_score_ignoring_cards": _plain(ignoring_cards),
    }


def _plain(value: object) -> Any:
    """A JSON-serializable copy of a numpy or pandas scalar; other values unchanged."""

    item = getattr(value, "item", None)
    return item() if callable(item) else value


def _detail(
    result: EvaluationResult,
    folds: tuple[EvaluationFold, ...],
    *,
    record_decisions: bool = False,
) -> list[_FoldDecisionDetail]:
    rows: list[_FoldDecisionDetail] = []
    for item, fold in zip(result.folds, folds, strict=True):
        if not item.optimization_result.has_solution:
            continue
        decision = complete_optimization_decision(item.optimization_result)
        scored = score_frozen_squad_decision(decision, fold.realized_points)
        minutes = dict(
            fold.realized_points[["player_id", "minutes"]].itertuples(index=False, name=None)
        )
        rows.append(
            _FoldDecisionDetail(
                fold_id=fold.fold_id,
                score=scored.total_points,
                zero_minute_starters=sum(
                    int(minutes[player_id]) == 0 for player_id in decision.starting_xi
                ),
                autosub_points=scored.autosub_points,
                vice_recovered=bool(
                    scored.captain_bonus_player_id == decision.vice_captain_id
                    and decision.vice_captain_id != decision.captain_id
                ),
                decision=(
                    _recorded_decision(item, decision, fold, scored.total_points)
                    if record_decisions
                    else {}
                ),
            )
        )
    return rows


def evaluate_phase_c_component_decisions(
    handoff: PhaseCComponentHandoff,
    control_folds: Iterable[EvaluationFold],
    config: EvaluationConfig,
    *,
    development_contract: str | None = None,
    record_decisions: bool = False,
) -> PhaseCDecisionComparison:
    """Compare component-base and historical control decisions without promoting either.

    ``development_contract`` admits a handoff read under the Phase C v2 development
    contract, and only that one; the frozen v1 path leaves it ``None`` and a development
    artifact is then refused, as :func:`prepare_phase_c_component_folds` states.
    ``record_decisions`` keeps each arm's solved squad, lineup, captaincy, objective, bound
    and both scores per fold on the result, for a measurement that reads them.
    """

    if not isinstance(config, EvaluationConfig):
        raise EvaluationValidationError("config must be an EvaluationConfig.")
    if config.scoring_policy is not ScoringPolicy.OFFICIAL_AUTOSUB_CAPTAIN_V2:
        raise EvaluationValidationError(
            "Phase C decision comparison requires official_autosub_captain_v2."
        )
    controls = _folds(control_folds)
    candidates = prepare_phase_c_component_folds(
        handoff, controls, development_contract=development_contract
    )
    normalized_controls = tuple(
        EvaluationFold(
            fold_id=control.fold_id,
            projections=control.projections,
            realized_points=candidate.realized_points,
            metadata=control.metadata,
        )
        for control, candidate in zip(controls, candidates, strict=True)
    )
    control_result = evaluate_prepared_folds(normalized_controls, config)
    candidate_result = evaluate_prepared_folds(candidates, config)
    control_detail = {
        row.fold_id: row
        for row in _detail(control_result, normalized_controls, record_decisions=record_decisions)
    }
    candidate_detail = {
        row.fold_id: row
        for row in _detail(candidate_result, candidates, record_decisions=record_decisions)
    }
    comparable_ids = [
        fold.fold_id
        for fold in controls
        if fold.fold_id in control_detail and fold.fold_id in candidate_detail
    ]
    differences = [
        candidate_detail[fold_id].score - control_detail[fold_id].score
        for fold_id in comparable_ids
    ]
    season_values: dict[str, list[float]] = {}
    for fold_id, difference in zip(comparable_ids, differences, strict=True):
        season_values.setdefault(fold_id[:7], []).append(difference)
    diagnostics = PhaseCDecisionDiagnostics(
        attempted_folds=len(controls),
        comparable_folds=len(comparable_ids),
        candidate_wins=sum(value > 0 for value in differences),
        ties=sum(value == 0 for value in differences),
        candidate_losses=sum(value < 0 for value in differences),
        mean_difference=fmean(differences) if differences else None,
        median_difference=median(differences) if differences else None,
        season_mean_differences={
            season: fmean(values) for season, values in sorted(season_values.items())
        },
        candidate_zero_minute_starters=sum(
            row.zero_minute_starters for row in candidate_detail.values()
        ),
        control_zero_minute_starters=sum(
            row.zero_minute_starters for row in control_detail.values()
        ),
        candidate_autosub_points=sum(row.autosub_points for row in candidate_detail.values()),
        control_autosub_points=sum(row.autosub_points for row in control_detail.values()),
        candidate_vice_captain_recoveries=sum(
            row.vice_recovered for row in candidate_detail.values()
        ),
        control_vice_captain_recoveries=sum(row.vice_recovered for row in control_detail.values()),
    )
    decisions = (
        {
            fold_id: {
                "control": control_detail[fold_id].decision,
                "component_base": candidate_detail[fold_id].decision,
            }
            for fold_id in comparable_ids
        }
        if record_decisions
        else {}
    )
    return PhaseCDecisionComparison(control_result, candidate_result, diagnostics, decisions)


__all__ = [
    "PhaseCDecisionComparison",
    "PhaseCDecisionDiagnostics",
    "evaluate_phase_c_component_decisions",
    "prepare_phase_c_component_folds",
]

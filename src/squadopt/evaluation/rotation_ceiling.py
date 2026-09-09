"""The ceiling a perfect rotation signal could reach, and the oracle that defines it.

Gate G0 of ``docs/rotation_evidence_prereg.md`` asks one question and nothing else:
*if* a rotation signal were perfect, applied as a default exclusion before the deadline,
what would it have been worth per decision on the development folds? The answer is a
ceiling. No reachable signal beats an oracle, so a ceiling below the promotion policy's
own ``min_mean_improvement`` says the pursuit is not worth its cost -- and a ceiling above
it says nothing whatever about *our* signal, which is measured under G1 and G2 instead.

**The oracle is hindsight, by construction.** It reads the target gameweek's own minutes,
which is exactly what every feature in this repository is forbidden to do. That is not a
loophole; it is the definition of a ceiling. The project's rule is that a gameweek's own
outcome may score a decision, never inform it, and this module is the one place that
deliberately stands outside it -- so it lives in ``evaluation/``, beside the scorers, and
produces no feature, no column and no model input. Nothing here is reachable from the
prediction path.

**What the oracle can and cannot see.** The development archive carries no verified start
labels (``START_TARGET_SUPPORTED_SEASONS`` is empty), so ``minutes > 0`` is the only
appearance signal there is. The oracle is therefore built on *playing*, not on *starting*:
a regular who started and was withdrawn at half time is not flagged, and a regular who
came off the bench for one minute is not flagged either. It marks the archive's closest
observable to "rested" -- a recent regular who did not play at all.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from statistics import fmean, median
from typing import Final, TypeAlias

import pandas as pd

from squadopt.data.schema import PLAYER_TIME_SORT_COLUMNS
from squadopt.evaluation.models import EvaluationError, EvaluationFold, EvaluationResult
from squadopt.evaluation.scoring import (
    complete_optimization_decision,
    score_frozen_squad_decision,
)
from squadopt.features import APPEARANCE_SOURCE_COLUMN, shifted_rolling_mean

#: This measurement's own contract. Bumped whenever the oracle rule, the arms or the
#: recorded fields change, because a record written under one version is not comparable
#: with one written under another.
ROTATION_CEILING_CONTRACT_VERSION: Final = "rotation_oracle_ceiling_v1"

#: The flagging rule, named so a later ceiling measured under a different rule cannot be
#: mistaken for a re-run of this one.
ORACLE_VERSION: Final = "rested_regular_oracle_v1"

#: How many gameweeks of history the appearance rate is taken over. Six is the window the
#: promoted minutes model already uses (``ExpectedMinutesConfig.window``), so the oracle
#: reads recency the same way the production path does rather than inventing a horizon.
ORACLE_APPEARANCE_WINDOW: Final = 6

#: A fold's identity as the panel spells it. Deliberately ``(season, gameweek)`` rather
#: than the ``2021-22-gw02`` string: that string's format belongs to
#: ``backtest.splits.DecisionPoint``, which sits above this layer, and a second copy of a
#: format is a second thing to keep in step.
FoldKey: TypeAlias = tuple[str, int]

_ORACLE_SOURCE_COLUMNS: Final[tuple[str, ...]] = ("season", "gameweek", "player_id", "minutes")

#: Tolerance when the two scoring paths are compared against each other. Both compute the
#: same Decimal sum and convert once, so they agree exactly in practice; the tolerance is
#: here so a float representation detail cannot fail a run that is in fact identical.
_SCORE_AGREEMENT_TOLERANCE: Final = 1e-9


class RotationCeilingError(EvaluationError):
    """The rotation ceiling could not be measured from what it was handed."""


@dataclass(frozen=True, slots=True)
class OracleFlags:
    """Whom a perfect signal would have excluded, and the counts behind that.

    ``by_fold`` is keyed by the decision the exclusion applies to. A fold absent from the
    mapping had nobody to exclude, which is a different statement from "the oracle was not
    run there" -- ``eligible_rows`` is what separates the two.
    """

    version: str
    window: int
    min_periods: int
    by_fold: Mapping[FoldKey, tuple[object, ...]]
    by_season: Mapping[str, int]
    panel_rows: int
    eligible_rows: int
    zero_minute_eligible_rows: int
    flagged_rows: int


@dataclass(frozen=True, slots=True)
class ExcludedFold:
    """One fold after the exclusion, and what the exclusion actually reached.

    ``absent`` is not an error. A flagged player may have no row in a fold's projection
    pool at all -- the projection layer drops a player it cannot project -- and an
    exclusion that cannot reach him changes nothing. Reporting the two separately is what
    keeps "excluded nobody" distinguishable from "had nobody to exclude".
    """

    fold: EvaluationFold
    applied: tuple[object, ...]
    absent: tuple[object, ...]


@dataclass(frozen=True, slots=True)
class FoldDecisionDetail:
    """One arm's scored decision for one fold, with the two mechanism counts."""

    fold_id: str
    season: str
    gameweek: int
    points: float
    zero_minute_starters: int
    autosub_points: float
    excluded_starters: int


@dataclass(frozen=True, slots=True)
class PairedFoldDifference:
    """One fold scored under both arms. The season travels with it for the interval."""

    fold_id: str
    season: str
    control_points: float
    oracle_points: float
    difference: float


@dataclass(frozen=True, slots=True)
class RotationCeilingComparison:
    """Both arms on identical folds, aggregated, promoting nothing.

    There is no verdict field here on purpose. The threshold G0 is read against lives in
    ``experiments.config.PromotionPolicy``, a layer above this one, so the comparison
    reports the paired difference and the caller that owns the policy applies it. That
    also keeps this object honest about what it is: a description, not a decision.
    """

    contract_version: str
    oracle_version: str
    appearance_window: int
    attempted_folds: int
    comparable_folds: int
    dropped_fold_ids: tuple[str, ...]
    oracle_wins: int
    ties: int
    oracle_losses: int
    mean_difference: float | None
    median_difference: float | None
    season_mean_differences: Mapping[str, float]
    control_mean_points: float | None
    oracle_mean_points: float | None
    control_zero_minute_starters: int
    oracle_zero_minute_starters: int
    control_autosub_points: float
    oracle_autosub_points: float
    control_started_excluded_players: int
    differences: tuple[PairedFoldDifference, ...]


def build_oracle_flags(
    panel: pd.DataFrame,
    *,
    window: int = ORACLE_APPEARANCE_WINDOW,
) -> OracleFlags:
    """Flag every recent regular who did not play, per decision.

    A player is flagged when he recorded **zero minutes** in the target gameweek *and* his
    shifted appearance rate over the previous ``window`` gameweeks is exactly 1.0 -- he
    featured in every one of them, and then did not feature at all. That is the archive's
    nearest observation to a manager resting a nailed-on starter.

    ``min_periods`` is set to ``window``, not left at the primitive's default of 1. This is
    the correctness point of the whole rule: with one prior observation a rate of 1.0 means
    "played once", and gameweek 2 would flag half the league. Requiring the full window
    means a rate of 1.0 is six appearances out of six, and a player without six prior
    gameweeks is not eligible rather than being read as a regular.

    The rate itself comes from :func:`squadopt.features.shifted_rolling_mean`, the project's
    single shifted-rolling primitive, so the *history* side of the rule cannot see the
    target gameweek. Only the ``minutes == 0`` half is hindsight, and it is hindsight
    deliberately -- see the module docstring.
    """

    if not isinstance(panel, pd.DataFrame):
        raise RotationCeilingError("panel must be a pandas DataFrame.")
    if isinstance(window, bool) or not isinstance(window, int) or window < 1:
        raise RotationCeilingError(f"window must be a positive integer, got {window!r}.")
    missing = [column for column in _ORACLE_SOURCE_COLUMNS if column not in panel.columns]
    if missing:
        raise RotationCeilingError(f"The panel is missing columns the oracle needs: {missing!r}.")

    # Sorted here so the primitive can verify the order rather than re-sort it, which is the
    # arrangement `features.builder` already relies on.
    ordered = (
        panel.loc[:, list(_ORACLE_SOURCE_COLUMNS)]
        .sort_values(list(PLAYER_TIME_SORT_COLUMNS), kind="stable")
        .reset_index(drop=True)
    )
    if bool(ordered["minutes"].isna().any()):
        raise RotationCeilingError(
            "The oracle reads minutes as an outcome; a missing value is not a zero and "
            "cannot be treated as one."
        )
    with_indicator = ordered.assign(
        **{APPEARANCE_SOURCE_COLUMN: (ordered["minutes"] > 0).astype("int64")}
    )
    rate = shifted_rolling_mean(
        with_indicator, APPEARANCE_SOURCE_COLUMN, window, min_periods=window
    )

    eligible = rate.notna()
    zero_minutes = ordered["minutes"] == 0
    flagged = eligible & (rate == 1.0) & zero_minutes

    rows = ordered.loc[flagged, ["season", "gameweek", "player_id"]]
    collected: dict[FoldKey, list[object]] = {}
    by_season: dict[str, int] = {}
    for season, gameweek, player_id in rows.itertuples(index=False, name=None):
        key = (str(season), int(gameweek))
        collected.setdefault(key, []).append(player_id)
        by_season[key[0]] = by_season.get(key[0], 0) + 1
    # Sorted by their text form so the recorded list is deterministic without assuming
    # whether this panel's identifiers are integers or strings.
    by_fold: dict[FoldKey, tuple[object, ...]] = {
        key: tuple(sorted(players, key=str)) for key, players in sorted(collected.items())
    }

    return OracleFlags(
        version=ORACLE_VERSION,
        window=window,
        min_periods=window,
        by_fold=by_fold,
        by_season=by_season,
        panel_rows=len(ordered),
        eligible_rows=int(eligible.sum()),
        zero_minute_eligible_rows=int((eligible & zero_minutes).sum()),
        flagged_rows=int(flagged.sum()),
    )


def fold_key(fold: EvaluationFold) -> FoldKey:
    """Return the ``(season, gameweek)`` a fold decides, or refuse.

    Refusing rather than skipping is the lesson of
    ``test_a_fold_without_its_season_in_metadata_stops_the_run``: a fold silently dropped
    for want of a metadata key would narrow every aggregate below the fold count the run
    reports, with no error anywhere.
    """

    season = fold.metadata.get("season")
    gameweek = fold.metadata.get("gameweek")
    if not isinstance(season, str) or not season:
        raise RotationCeilingError(
            f"Fold {fold.fold_id!r} does not name its season in metadata; the oracle is "
            "matched to a decision by season and gameweek, not by fold id."
        )
    if isinstance(gameweek, bool) or not isinstance(gameweek, int):
        raise RotationCeilingError(
            f"Fold {fold.fold_id!r} does not name its gameweek in metadata as an integer."
        )
    return (season, gameweek)


def attach_realized_minutes(fold: EvaluationFold, panel: pd.DataFrame) -> EvaluationFold:
    """Return the fold with realized minutes joined onto its realized points.

    ``backtest.splits.realized_points_at`` returns ``player_id`` and ``total_points`` only,
    while the official autosub policy needs minutes to know who did not play. Rather than
    widen that function -- it is the answer-sheet reader for every other caller -- the
    minutes are joined here, from the same panel rows the outcomes came from.
    """

    if "minutes" in fold.realized_points.columns:
        raise RotationCeilingError(
            f"Fold {fold.fold_id!r} already carries realized minutes. Joining a second "
            "minutes column would leave two answers to one question."
        )
    season, gameweek = fold_key(fold)
    rows = panel.loc[
        (panel["season"] == season) & (panel["gameweek"] == gameweek),
        ["player_id", "minutes"],
    ]
    if rows.empty:
        raise RotationCeilingError(
            f"The panel holds no rows for {season} gameweek {gameweek}; a gameweek that is "
            "absent cannot supply the minutes that score it."
        )
    if bool(rows["player_id"].duplicated().any()):
        raise RotationCeilingError(
            f"{season} gameweek {gameweek} repeats a player_id, so its minutes are ambiguous."
        )
    merged = fold.realized_points.merge(rows, on="player_id", how="left", validate="one_to_one")
    unmatched = merged.loc[merged["minutes"].isna(), "player_id"].tolist()
    if unmatched:
        raise RotationCeilingError(
            f"{len(unmatched)} scored player(s) in fold {fold.fold_id!r} have no minutes in "
            f"the panel; examples: {unmatched[:5]!r}."
        )
    merged["minutes"] = merged["minutes"].astype("int64")
    return EvaluationFold(
        fold_id=fold.fold_id,
        projections=fold.projections,
        realized_points=merged,
        metadata=fold.metadata,
    )


def apply_rotation_exclusion(fold: EvaluationFold, excluded: Iterable[object]) -> ExcludedFold:
    """Zero the expected points of the excluded players, and keep their rows.

    This is the availability rule's *position* and its *direction*: after the projection is
    built, before the squad is solved, and downward only. It is the shape a real rotation
    signal would have to take, so the ceiling is measured on the shape of the thing rather
    than on a more convenient one.

    The rows stay. ``AvailabilityAdjustment`` gives the reason in its own docstring --
    unavailable players are "reported rather than removed" because pool membership is a
    decision-layer concern and dropping rows can turn a squad problem infeasible for
    reasons the decision layer never sees. Here it would also destroy the pairing: a fold
    that goes infeasible in one arm leaves no difference to measure.

    ``FirstWeekOverlap`` is deliberately not used. That constraint binds the first week's
    squad variables, which means *keeping* a player in the squad and forces a transfer to
    change him. A rotation signal says who not to start, not who to sell.
    """

    for column in ("player_id", "expected_points"):
        if column not in fold.projections.columns:
            raise RotationCeilingError(
                f"Fold {fold.fold_id!r} projections are missing {column!r}; the exclusion "
                "writes expected points and cannot invent the table it writes into."
            )
    requested = tuple(excluded)
    pool = set(fold.projections["player_id"].tolist())
    applied = tuple(player_id for player_id in requested if player_id in pool)
    absent = tuple(player_id for player_id in requested if player_id not in pool)

    projections = fold.projections.copy(deep=True)
    if applied:
        projections.loc[projections["player_id"].isin(list(applied)), "expected_points"] = 0.0
    return ExcludedFold(
        fold=EvaluationFold(
            fold_id=fold.fold_id,
            projections=projections,
            realized_points=fold.realized_points,
            metadata={**dict(fold.metadata), "rotation_excluded_players": len(applied)},
        ),
        applied=applied,
        absent=absent,
    )


def fold_decision_details(
    result: EvaluationResult,
    folds: Sequence[EvaluationFold],
    *,
    excluded_by_fold: Mapping[FoldKey, tuple[object, ...]],
) -> tuple[FoldDecisionDetail, ...]:
    """Re-read each scored fold for the two mechanism counts the summary does not carry.

    ``EvaluationResult`` reports realized squad points but neither the zero-minute starter
    count nor the autosub points, so the frozen decision is completed and scored again --
    no solve, only arithmetic over a decision that is already fixed. The recomputed total
    is checked against the evaluator's own, which is what makes this a second reading of
    one decision rather than a second definition of the score.

    ``component_decisions._detail`` computes the same three numbers for the Phase C arms.
    The duplication is deliberate: promoting that private helper would change a module this
    lane may not touch. On the rule of three, a shared helper is the right next move.
    """

    details: list[FoldDecisionDetail] = []
    for item, fold in zip(result.folds, folds, strict=True):
        if item.fold_id != fold.fold_id:
            raise RotationCeilingError(
                f"Result and fold order disagree: {item.fold_id!r} against {fold.fold_id!r}."
            )
        if not item.optimization_result.has_solution:
            continue
        decision = complete_optimization_decision(item.optimization_result)
        scored = score_frozen_squad_decision(decision, fold.realized_points)
        if item.realized_squad_points is None:
            raise RotationCeilingError(
                f"Fold {fold.fold_id!r} solved but was not scored; the two readings cannot "
                "be reconciled."
            )
        if abs(scored.total_points - item.realized_squad_points) > _SCORE_AGREEMENT_TOLERANCE:
            raise RotationCeilingError(
                f"Fold {fold.fold_id!r} scores {scored.total_points} on re-reading and "
                f"{item.realized_squad_points} in the evaluation result."
            )
        minutes = dict(
            fold.realized_points[["player_id", "minutes"]].itertuples(index=False, name=None)
        )
        season, gameweek = fold_key(fold)
        excluded = set(excluded_by_fold.get((season, gameweek), ()))
        details.append(
            FoldDecisionDetail(
                fold_id=fold.fold_id,
                season=season,
                gameweek=gameweek,
                points=scored.total_points,
                # The nominal XI, before autosubs. That is the count an exclusion is meant
                # to move: an autosub repairs the damage afterwards, it does not undo the
                # selection.
                zero_minute_starters=sum(
                    int(minutes[player_id]) == 0 for player_id in decision.starting_xi
                ),
                autosub_points=scored.autosub_points,
                excluded_starters=sum(player_id in excluded for player_id in decision.starting_xi),
            )
        )
    return tuple(details)


def compare_rotation_ceiling(
    control_details: Sequence[FoldDecisionDetail],
    oracle_details: Sequence[FoldDecisionDetail],
    *,
    attempted_folds: int,
) -> RotationCeilingComparison:
    """Pair the two arms fold by fold and aggregate, deciding nothing.

    Paired, never mean-by-mean: subtracting two averages answers a different question than
    pairing the folds does, and the gate is written on the paired one. A fold scored in one
    arm and not the other is dropped from the pairing and named in ``dropped_fold_ids``, so
    a narrowed population is visible rather than implied.
    """

    control_by_id = {detail.fold_id: detail for detail in control_details}
    oracle_by_id = {detail.fold_id: detail for detail in oracle_details}
    shared = sorted(set(control_by_id) & set(oracle_by_id))
    dropped = tuple(sorted(set(control_by_id) ^ set(oracle_by_id)))

    differences = tuple(
        PairedFoldDifference(
            fold_id=fold_id,
            season=control_by_id[fold_id].season,
            control_points=control_by_id[fold_id].points,
            oracle_points=oracle_by_id[fold_id].points,
            difference=oracle_by_id[fold_id].points - control_by_id[fold_id].points,
        )
        for fold_id in shared
    )
    values = [item.difference for item in differences]
    season_values: dict[str, list[float]] = {}
    for item in differences:
        season_values.setdefault(item.season, []).append(item.difference)

    return RotationCeilingComparison(
        contract_version=ROTATION_CEILING_CONTRACT_VERSION,
        oracle_version=ORACLE_VERSION,
        appearance_window=ORACLE_APPEARANCE_WINDOW,
        attempted_folds=attempted_folds,
        comparable_folds=len(differences),
        dropped_fold_ids=dropped,
        oracle_wins=sum(value > 0.0 for value in values),
        ties=sum(value == 0.0 for value in values),
        oracle_losses=sum(value < 0.0 for value in values),
        mean_difference=fmean(values) if values else None,
        median_difference=float(median(values)) if values else None,
        season_mean_differences={
            season: fmean(items) for season, items in sorted(season_values.items())
        },
        control_mean_points=(
            fmean(control_by_id[fold_id].points for fold_id in shared) if shared else None
        ),
        oracle_mean_points=(
            fmean(oracle_by_id[fold_id].points for fold_id in shared) if shared else None
        ),
        control_zero_minute_starters=sum(
            control_by_id[fold_id].zero_minute_starters for fold_id in shared
        ),
        oracle_zero_minute_starters=sum(
            oracle_by_id[fold_id].zero_minute_starters for fold_id in shared
        ),
        control_autosub_points=sum(control_by_id[fold_id].autosub_points for fold_id in shared),
        oracle_autosub_points=sum(oracle_by_id[fold_id].autosub_points for fold_id in shared),
        control_started_excluded_players=sum(
            control_by_id[fold_id].excluded_starters for fold_id in shared
        ),
        differences=differences,
    )


__all__ = [
    "ORACLE_APPEARANCE_WINDOW",
    "ORACLE_VERSION",
    "ROTATION_CEILING_CONTRACT_VERSION",
    "ExcludedFold",
    "FoldDecisionDetail",
    "FoldKey",
    "OracleFlags",
    "PairedFoldDifference",
    "RotationCeilingComparison",
    "RotationCeilingError",
    "apply_rotation_exclusion",
    "attach_realized_minutes",
    "build_oracle_flags",
    "compare_rotation_ceiling",
    "fold_decision_details",
    "fold_key",
]

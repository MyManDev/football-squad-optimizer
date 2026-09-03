"""Leakage-agnostic scoring of already-produced Phase C OOF component rows."""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from numbers import Integral, Real
from types import MappingProxyType
from typing import Final

import pandas as pd

from squadopt.evaluation.appearance import (
    APPEARANCE_LOG_LOSS_EPSILON,
    APPEARANCE_RELIABILITY_BIN_COUNT,
    AppearanceReliabilityBin,
)
from squadopt.evaluation.models import EvaluationValidationError

PHASE_C_COMPONENT_METRICS_VERSION: Final = "phase_c_component_metrics_v1"
PHASE_C_LOCKED_HOLDOUT_SEASONS: Final = frozenset(("2025-26",))
PHASE_C_OOF_KEY: Final = ("season", "target_gameweek", "player_id")
PHASE_C_OOF_REQUIRED_COLUMNS: Final = (
    *PHASE_C_OOF_KEY,
    "fold_id",
    "position",
    "fixture_count",
    "appearance_target",
    "start_target",
    "minutes_target",
    "points_target",
    "appearance_probability",
    "q_start_given_appearance",
    "start_probability",
    "expected_minutes_if_appearance",
    "expected_minutes",
    "expected_points_if_appearance",
    "expected_points",
)
_POSITIONS: Final = frozenset(("GK", "DEF", "MID", "FWD"))
_PROBABILITIES: Final = (
    "appearance_probability",
    "q_start_given_appearance",
    "start_probability",
)
_NON_NEGATIVE_PREDICTIONS: Final = (
    "expected_minutes_if_appearance",
    "expected_minutes",
    "expected_points",
)
_COMPOSITION_TOLERANCE: Final = 1e-9


@dataclass(frozen=True, slots=True)
class BinaryMetrics:
    """Proper scores and calibration summaries for one binary target."""

    observations: int
    brier_score: float | None
    log_loss: float | None
    mean_prediction: float | None
    event_rate: float | None
    mean_calibration_bias: float | None
    reliability_bins: tuple[AppearanceReliabilityBin, ...] = ()


@dataclass(frozen=True, slots=True)
class ErrorMetrics:
    """Signed and unsigned errors for one numeric target."""

    observations: int
    mean_absolute_error: float | None
    root_mean_squared_error: float | None
    mean_error: float | None


@dataclass(frozen=True, slots=True)
class ComponentMetricSet:
    """Component metrics for one explicitly named population slice."""

    population_rows: int
    blank_rows: int
    missing_appearance_target_rows: int
    missing_appearance_prediction_rows: int
    missing_start_label_rows: int
    missing_start_prediction_rows: int
    missing_minutes_target_rows: int
    missing_minutes_prediction_rows: int
    missing_points_target_rows: int
    missing_points_prediction_rows: int
    appearance: BinaryMetrics
    start: BinaryMetrics
    start_given_appearance: BinaryMetrics
    minutes: ErrorMetrics
    minutes_if_appearance: ErrorMetrics
    points: ErrorMetrics
    points_if_appearance: ErrorMetrics


@dataclass(frozen=True, slots=True)
class PhaseCComponentEvaluation:
    """Overall and descriptive-slice scores for one Phase C OOF arm."""

    overall: ComponentMetricSet
    by_season: Mapping[str, ComponentMetricSet]
    by_position: Mapping[str, ComponentMetricSet]
    by_fixture_group: Mapping[str, ComponentMetricSet]
    contract_version: str = PHASE_C_COMPONENT_METRICS_VERSION

    def __post_init__(self) -> None:
        for name in ("by_season", "by_position", "by_fixture_group"):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))


def _numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    values = frame[column]
    invalid = [
        value
        for value in values.tolist()
        if not pd.isna(value) and (isinstance(value, bool) or not isinstance(value, Real))
    ]
    if invalid:
        raise EvaluationValidationError(f"{column} must contain finite numbers or missing values.")
    numeric = pd.to_numeric(values, errors="raise").astype("float64")
    if bool(numeric.dropna().map(lambda value: not math.isfinite(value)).any()):
        raise EvaluationValidationError(f"{column} must contain finite numbers or missing values.")
    return numeric


def _integer_column(frame: pd.DataFrame, column: str, *, minimum: int) -> pd.Series:
    values = frame[column].tolist()
    if any(
        isinstance(value, bool) or not isinstance(value, Integral) or int(value) < minimum
        for value in values
    ):
        raise EvaluationValidationError(f"{column} must contain integers of at least {minimum}.")
    return pd.Series((int(value) for value in values), index=frame.index, dtype="int64")


def _validate_binary_target(frame: pd.DataFrame, column: str) -> pd.Series:
    numeric = _numeric(frame, column)
    if bool((~numeric.dropna().isin((0.0, 1.0))).any()):
        raise EvaluationValidationError(f"{column} must contain only 0, 1 or missing values.")
    return numeric


def _validate_oof(value: object) -> pd.DataFrame:
    if not isinstance(value, pd.DataFrame):
        raise EvaluationValidationError("oof_rows must be a pandas DataFrame.")
    duplicates = value.columns[value.columns.duplicated()].tolist()
    if duplicates:
        raise EvaluationValidationError(f"oof_rows has duplicate columns: {duplicates[:10]!r}.")
    missing = [column for column in PHASE_C_OOF_REQUIRED_COLUMNS if column not in value]
    if missing:
        raise EvaluationValidationError(f"oof_rows is missing columns: {missing!r}.")
    frame = value.loc[:, list(PHASE_C_OOF_REQUIRED_COLUMNS)].copy(deep=True)
    if frame.empty:
        raise EvaluationValidationError("oof_rows must contain at least one row.")
    if bool(frame[list(PHASE_C_OOF_KEY)].isna().any().any()):
        raise EvaluationValidationError("Phase C OOF keys must not be missing.")
    if bool(frame.duplicated(subset=list(PHASE_C_OOF_KEY)).any()):
        raise EvaluationValidationError("Phase C OOF keys must be unique.")
    frame["target_gameweek"] = _integer_column(frame, "target_gameweek", minimum=1)
    frame["fixture_count"] = _integer_column(frame, "fixture_count", minimum=0)
    if bool(frame["season"].map(lambda item: not isinstance(item, str) or not item.strip()).any()):
        raise EvaluationValidationError("season must contain non-empty strings.")
    if bool(frame["fold_id"].map(lambda item: not isinstance(item, str) or not item.strip()).any()):
        raise EvaluationValidationError("fold_id must contain non-empty strings.")
    if bool((~frame["position"].isin(_POSITIONS)).any()):
        raise EvaluationValidationError("position must contain only GK, DEF, MID or FWD.")
    if bool(frame["season"].isin(PHASE_C_LOCKED_HOLDOUT_SEASONS).any()):
        raise EvaluationValidationError("The locked 2025-26 holdout must not be evaluated.")

    player_ids = frame["player_id"].tolist()
    if any(isinstance(value, bool) for value in player_ids):
        raise EvaluationValidationError("player_id must not contain bool values.")
    player_id_kinds = {
        "integer"
        if isinstance(value, Integral)
        else "string"
        if isinstance(value, str)
        else "other"
        for value in player_ids
    }
    if player_id_kinds == {"string"}:
        if any(not value.strip() for value in player_ids):
            raise EvaluationValidationError("player_id strings must not be empty.")
    elif player_id_kinds != {"integer"}:
        raise EvaluationValidationError(
            "player_id must use one consistent representation: non-empty strings or integers."
        )

    frame["appearance_target"] = _validate_binary_target(frame, "appearance_target")
    frame["start_target"] = _validate_binary_target(frame, "start_target")
    for column in (
        "minutes_target",
        "points_target",
        *_PROBABILITIES,
        *_NON_NEGATIVE_PREDICTIONS,
        "expected_points_if_appearance",
    ):
        frame[column] = _numeric(frame, column)

    if bool(frame["minutes_target"].dropna().lt(0.0).any()):
        raise EvaluationValidationError("minutes_target must be non-negative when observed.")
    known_minutes = frame["minutes_target"].notna()
    expected_appearance = frame["minutes_target"].gt(0.0).astype("float64")
    if bool(
        frame.loc[known_minutes, "appearance_target"].isna().any()
        or (
            frame.loc[known_minutes, "appearance_target"] != expected_appearance.loc[known_minutes]
        ).any()
    ):
        raise EvaluationValidationError(
            "appearance_target must equal one exactly when minutes > 0."
        )
    if bool((frame["appearance_target"].notna() & frame["minutes_target"].isna()).any()):
        raise EvaluationValidationError(
            "An observed appearance_target requires observed minutes_target."
        )
    if bool(frame.loc[frame["start_target"].eq(1.0), "appearance_target"].ne(1.0).any()):
        raise EvaluationValidationError("A verified start must imply an appearance.")

    for column in _PROBABILITIES:
        observed = frame[column].dropna()
        if bool(observed.lt(0.0).any() or observed.gt(1.0).any()):
            raise EvaluationValidationError(f"{column} must lie in [0, 1].")
    paired_start = frame["q_start_given_appearance"].notna()
    if bool(paired_start.ne(frame["start_probability"].notna()).any()):
        raise EvaluationValidationError(
            "q_start_given_appearance and start_probability must be available together."
        )
    if bool((paired_start & frame["appearance_probability"].isna()).any()):
        raise EvaluationValidationError("A start prediction requires appearance_probability.")
    composed_start = frame["appearance_probability"] * frame["q_start_given_appearance"]
    if bool(
        ~frame.loc[paired_start, "start_probability"]
        .combine(
            composed_start.loc[paired_start],
            lambda actual, expected: math.isclose(
                float(actual),
                float(expected),
                rel_tol=0.0,
                abs_tol=_COMPOSITION_TOLERANCE,
            ),
        )
        .all()
    ):
        raise EvaluationValidationError(
            "start_probability must equal appearance_probability * q_start_given_appearance."
        )

    appearance_prediction = frame["appearance_probability"].notna()
    for conditional, composed in (
        ("expected_minutes_if_appearance", "expected_minutes"),
        ("expected_points_if_appearance", "expected_points"),
    ):
        if bool(frame[conditional].notna().ne(appearance_prediction).any()):
            raise EvaluationValidationError(
                f"{conditional} must be available exactly when appearance_probability is available."
            )
        if bool(frame[composed].notna().ne(appearance_prediction).any()):
            raise EvaluationValidationError(
                f"{composed} must be available exactly when appearance_probability is available."
            )
        expected = frame["appearance_probability"] * frame[conditional]
        if bool(
            ~frame.loc[appearance_prediction, composed]
            .combine(
                expected.loc[appearance_prediction],
                lambda actual, wanted: math.isclose(
                    float(actual),
                    float(wanted),
                    rel_tol=0.0,
                    abs_tol=_COMPOSITION_TOLERANCE,
                ),
            )
            .all()
        ):
            raise EvaluationValidationError(
                f"{composed} must equal appearance_probability * {conditional}."
            )

    for column in _NON_NEGATIVE_PREDICTIONS:
        if bool(frame[column].dropna().lt(0.0).any()):
            raise EvaluationValidationError(f"{column} must be non-negative when available.")
    minute_limit = frame["fixture_count"].mul(90.0)
    for column in ("expected_minutes", "expected_minutes_if_appearance"):
        observed = frame[column].notna()
        if bool(frame.loc[observed, column].gt(minute_limit.loc[observed]).any()):
            raise EvaluationValidationError(f"{column} cannot exceed 90 * fixture_count.")

    blank = frame["fixture_count"].eq(0)
    for column in (
        "appearance_probability",
        "q_start_given_appearance",
        "start_probability",
        "expected_minutes_if_appearance",
        "expected_minutes",
        "expected_points_if_appearance",
        "expected_points",
    ):
        if bool(frame.loc[blank, column].dropna().ne(0.0).any()):
            raise EvaluationValidationError(f"Blank-gameweek {column} must be zero when available.")
    for column in (
        "appearance_target",
        "start_target",
        "minutes_target",
        "points_target",
    ):
        if bool(frame.loc[blank, column].dropna().ne(0.0).any()):
            raise EvaluationValidationError(f"Blank-gameweek {column} must be zero when observed.")

    decision_keys = frame.loc[:, ["season", "target_gameweek", "fold_id"]].drop_duplicates()
    if bool(decision_keys.duplicated(subset=["season", "target_gameweek"]).any()) or bool(
        decision_keys.duplicated(subset=["fold_id"]).any()
    ):
        raise EvaluationValidationError(
            "fold_id and (season, target_gameweek) must identify each other uniquely."
        )

    frame["fixture_group"] = frame["fixture_count"].map(
        lambda count: "blank" if count == 0 else "single" if count == 1 else "double_plus"
    )
    return frame.sort_values(list(PHASE_C_OOF_KEY), kind="stable").reset_index(drop=True)


def _empty_bins() -> tuple[AppearanceReliabilityBin, ...]:
    return tuple(
        AppearanceReliabilityBin(
            index=index,
            lower_bound=index / APPEARANCE_RELIABILITY_BIN_COUNT,
            upper_bound=(index + 1) / APPEARANCE_RELIABILITY_BIN_COUNT,
            observations=0,
            mean_probability=None,
            appearance_rate=None,
        )
        for index in range(APPEARANCE_RELIABILITY_BIN_COUNT)
    )


def _binary_metrics(
    frame: pd.DataFrame,
    prediction: str,
    target: str,
    *,
    reliability: bool = False,
) -> BinaryMetrics:
    scored = frame.loc[frame[prediction].notna() & frame[target].notna(), [prediction, target]]
    if scored.empty:
        return BinaryMetrics(0, None, None, None, None, None, _empty_bins() if reliability else ())
    probability = scored[prediction]
    outcome = scored[target]
    clipped = probability.clip(
        lower=APPEARANCE_LOG_LOSS_EPSILON,
        upper=1.0 - APPEARANCE_LOG_LOSS_EPSILON,
    )
    bins: tuple[AppearanceReliabilityBin, ...] = ()
    if reliability:
        indices = probability.mul(APPEARANCE_RELIABILITY_BIN_COUNT).astype(int)
        indices = indices.clip(upper=APPEARANCE_RELIABILITY_BIN_COUNT - 1)
        records = []
        for index in range(APPEARANCE_RELIABILITY_BIN_COUNT):
            rows = scored.loc[indices == index]
            records.append(
                AppearanceReliabilityBin(
                    index=index,
                    lower_bound=index / APPEARANCE_RELIABILITY_BIN_COUNT,
                    upper_bound=(index + 1) / APPEARANCE_RELIABILITY_BIN_COUNT,
                    observations=len(rows),
                    mean_probability=None if rows.empty else float(rows[prediction].mean()),
                    appearance_rate=None if rows.empty else float(rows[target].mean()),
                )
            )
        bins = tuple(records)
    return BinaryMetrics(
        observations=len(scored),
        brier_score=float(probability.sub(outcome).pow(2).mean()),
        log_loss=float(
            -(
                outcome.mul(clipped.map(math.log))
                + (1.0 - outcome).mul((1.0 - clipped).map(math.log))
            ).mean()
        ),
        mean_prediction=float(probability.mean()),
        event_rate=float(outcome.mean()),
        mean_calibration_bias=float(probability.mean() - outcome.mean()),
        reliability_bins=bins,
    )


def _error_metrics(frame: pd.DataFrame, prediction: str, target: str) -> ErrorMetrics:
    scored = frame.loc[frame[prediction].notna() & frame[target].notna(), [prediction, target]]
    if scored.empty:
        return ErrorMetrics(0, None, None, None)
    error = scored[prediction] - scored[target]
    return ErrorMetrics(
        observations=len(scored),
        mean_absolute_error=float(error.abs().mean()),
        root_mean_squared_error=float(error.pow(2).mean() ** 0.5),
        mean_error=float(error.mean()),
    )


def _score(frame: pd.DataFrame) -> ComponentMetricSet:
    non_blank = frame.loc[frame["fixture_count"].gt(0)]
    appeared = non_blank.loc[non_blank["appearance_target"].eq(1.0)]
    return ComponentMetricSet(
        population_rows=len(frame),
        blank_rows=int(frame["fixture_count"].eq(0).sum()),
        missing_appearance_target_rows=int(non_blank["appearance_target"].isna().sum()),
        missing_appearance_prediction_rows=int(
            (
                non_blank["appearance_target"].notna() & non_blank["appearance_probability"].isna()
            ).sum()
        ),
        missing_start_label_rows=int(non_blank["start_target"].isna().sum()),
        missing_start_prediction_rows=int(
            (non_blank["start_target"].notna() & non_blank["start_probability"].isna()).sum()
        ),
        missing_minutes_target_rows=int(non_blank["minutes_target"].isna().sum()),
        missing_minutes_prediction_rows=int(
            (non_blank["minutes_target"].notna() & non_blank["expected_minutes"].isna()).sum()
        ),
        missing_points_target_rows=int(non_blank["points_target"].isna().sum()),
        missing_points_prediction_rows=int(
            (non_blank["points_target"].notna() & non_blank["expected_points"].isna()).sum()
        ),
        appearance=_binary_metrics(
            non_blank, "appearance_probability", "appearance_target", reliability=True
        ),
        start=_binary_metrics(non_blank, "start_probability", "start_target"),
        start_given_appearance=_binary_metrics(
            appeared, "q_start_given_appearance", "start_target"
        ),
        minutes=_error_metrics(non_blank, "expected_minutes", "minutes_target"),
        minutes_if_appearance=_error_metrics(
            appeared, "expected_minutes_if_appearance", "minutes_target"
        ),
        points=_error_metrics(non_blank, "expected_points", "points_target"),
        points_if_appearance=_error_metrics(
            appeared, "expected_points_if_appearance", "points_target"
        ),
    )


def _slices(frame: pd.DataFrame, column: str) -> Mapping[str, ComponentMetricSet]:
    return MappingProxyType(
        {
            str(label): _score(rows)
            for label, rows in frame.groupby(column, sort=True, observed=True)
        }
    )


def evaluate_component_oof(oof_rows: pd.DataFrame) -> PhaseCComponentEvaluation:
    """Score validated component rows without independently proving OOF chronology."""

    frame = _validate_oof(oof_rows)
    return PhaseCComponentEvaluation(
        overall=_score(frame),
        by_season=_slices(frame, "season"),
        by_position=_slices(frame, "position"),
        by_fixture_group=_slices(frame, "fixture_group"),
    )


__all__ = [
    "PHASE_C_COMPONENT_METRICS_VERSION",
    "PHASE_C_LOCKED_HOLDOUT_SEASONS",
    "PHASE_C_OOF_KEY",
    "PHASE_C_OOF_REQUIRED_COLUMNS",
    "BinaryMetrics",
    "ComponentMetricSet",
    "ErrorMetrics",
    "PhaseCComponentEvaluation",
    "evaluate_component_oof",
]

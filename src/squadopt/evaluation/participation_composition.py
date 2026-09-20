"""Compose the control's points side through the conditional start probability, and read it.

The control prices a player as ``p_appearance * E[points | appearance]``: one conditional
points model over every row where the player took the field. ``q_start_given_appearance``
says which of two states that appearance was, and the states are not alike -- a starter
reached sixty minutes with probability 0.955 and a substitute with 0.004 over the live
season's 1890 player-gameweeks, and sixty minutes is where the second appearance point and
clean-sheet eligibility sit. So the composition this module builds is

.. code-block:: text

    composed = p_appearance * (q * E[points | start] + (1 - q) * E[points | substitute])

against the control's own

.. code-block:: text

    uncomposed = p_appearance * E[points | appearance]

**Three arms, not two**, because two cannot separate two different claims. Splitting the
points model by state is one change; knowing *which* player starts is another, and the
second arrives with a feature the first does not have (``q`` carries team strength, which
the control's points design does not). The middle arm replaces ``q`` with a scalar -- the
training season's own start rate among appeared rows -- so it splits the points model by
state while knowing nothing about who starts. A difference that survives the middle arm is
a state split; a difference that only appears in the third is rotation knowledge.

Every arm shares one appearance model and one training season, so nothing here reads as the
composition when it is really a training window. The three differ in the points side alone.

This module fits and composes. It does not decide what any of it means, does not promote,
and states no gate: the archive declares ``starts`` over two seasons
(:data:`squadopt.features.component_targets.START_TARGET_SUPPORTED_SEASONS`), one is spent
on the fit, and one judged season is not enough to carry a threshold.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge  # type: ignore[import-untyped]
from sklearn.pipeline import Pipeline, make_pipeline  # type: ignore[import-untyped]
from sklearn.preprocessing import StandardScaler  # type: ignore[import-untyped]

from squadopt.prediction.component_models import ComponentModelConfig, complete_feature_rows
from squadopt.prediction.config import PredictionConfigurationError

#: Identifies this reading in a record. It moves when the arms' meaning moves.
PARTICIPATION_COMPOSITION_CONTRACT_VERSION: Final = "participation_composition_v1"

#: The three arms, in the order they are read: each one change further from the control.
ARM_NAMES: Final = ("uncomposed", "state_split", "composed")

#: The realized states a row can land in, named so an absence is not read as a zero score.
STATE_LABELS: Final = ("absent", "substitute", "start")


@dataclass(frozen=True, slots=True)
class StatePointsModels:
    """The control's conditional points estimator, fitted three times on three row sets.

    ``pooled`` is the control's own fit over every appeared row. ``started`` and
    ``substitute`` are the same estimator, same design, same alpha, over the two disjoint
    halves of that set. Keeping the pooled fit here rather than reading it from elsewhere is
    what makes the arms comparable: all three come from one training season and one call.
    """

    pooled: Pipeline
    started: Pipeline
    substitute: Pipeline
    feature_columns: tuple[str, ...]
    pooled_rows: int
    started_rows: int
    substitute_rows: int
    #: The share of appeared training rows that were starts. The middle arm's scalar.
    training_start_rate: float


def _design(frame: pd.DataFrame, columns: Sequence[str]) -> "np.ndarray[Any, Any]":
    """The control's own design, coerced the control's way, as a matrix an estimator takes.

    ``pd.to_numeric(errors="coerce")`` rather than a hard cast, so a non-numeric value lands
    as a missing feature and the row is excluded by :func:`complete_feature_rows` instead of
    ending the run. Two designs that disagree about that are two models.
    """

    numeric = frame.loc[:, list(columns)].apply(pd.to_numeric, errors="coerce")
    design: np.ndarray[Any, Any] = numeric.to_numpy(dtype="float64")
    return design


def _ridge(alpha: float) -> Pipeline:
    """The control's conditional points estimator, built the way the control builds it."""

    return make_pipeline(StandardScaler(), Ridge(alpha=alpha, solver="cholesky"))


def realized_state(
    appearance_target: "pd.Series[Any]", start_target: "pd.Series[Any]"
) -> "pd.Series[Any]":
    """Which of the three states each row landed in, or ``pd.NA`` when the label is absent.

    The two labels are passed separately rather than read off one frame by name, because the
    frozen out-of-fold table carries a ``start_target`` column that is empty on every row: it
    was written before the archive's start label was declared. A reader that took both labels
    from that frame would silently call every appearance unlabelled.

    A row outside the declared start population has an appearance but no start label, and it
    is left missing rather than called a substitute. Absent is not zero.
    """

    appeared = pd.to_numeric(appearance_target, errors="coerce") == 1
    started = pd.to_numeric(start_target, errors="coerce")
    state = pd.Series(pd.NA, index=appeared.index, dtype="string")
    state.loc[~appeared] = "absent"
    state.loc[appeared & (started == 1)] = "start"
    state.loc[appeared & (started == 0)] = "substitute"
    return state


def fit_state_points(
    training: pd.DataFrame,
    *,
    feature_columns: Sequence[str],
    config: ComponentModelConfig | None = None,
) -> StatePointsModels | None:
    """Fit the pooled and the two state-conditional points models, or refuse.

    ``None`` when any of the three row sets is thinner than the control's own minimum. A
    ridge fitted on a handful of rows returns a number, and nothing downstream can tell that
    number from a measured one, which is why the refusal is explicit.
    """

    settings = ComponentModelConfig() if config is None else config
    if not isinstance(training, pd.DataFrame):
        raise PredictionConfigurationError("fit_state_points expects a pandas DataFrame.")
    columns = tuple(str(column) for column in feature_columns)
    if not columns:
        raise PredictionConfigurationError("At least one feature column is required.")

    usable = training.loc[complete_feature_rows(training, columns)]
    state = realized_state(usable["appearance_target"], usable["start_target"])
    scorable = pd.to_numeric(usable["points_target"], errors="coerce").notna()
    appeared = usable.loc[scorable & state.isin(["start", "substitute"])]
    appeared_state = state.loc[appeared.index]
    started = appeared.loc[appeared_state == "start"]
    substitute = appeared.loc[appeared_state == "substitute"]
    minimum = settings.minimum_training_rows
    if min(len(appeared), len(started), len(substitute)) < minimum:
        return None

    def target(frame: pd.DataFrame) -> "np.ndarray[Any, Any]":
        return pd.to_numeric(frame["points_target"], errors="raise").to_numpy(dtype="float64")

    pooled = _ridge(settings.points_alpha)
    pooled.fit(_design(appeared, columns), target(appeared))
    start_model = _ridge(settings.points_alpha)
    start_model.fit(_design(started, columns), target(started))
    substitute_model = _ridge(settings.points_alpha)
    substitute_model.fit(_design(substitute, columns), target(substitute))

    return StatePointsModels(
        pooled=pooled,
        started=start_model,
        substitute=substitute_model,
        feature_columns=columns,
        pooled_rows=len(appeared),
        started_rows=len(started),
        substitute_rows=len(substitute),
        training_start_rate=len(started) / len(appeared),
    )


def state_points(models: StatePointsModels, scoring: pd.DataFrame) -> pd.DataFrame:
    """The three conditional points predictions, clipped at zero where the control clips.

    The control clips its composed value at zero at the model's own output boundary, and the
    same clip is applied to each state's conditional value here so that one arm is not
    allowed a negative price the other refuses.
    """

    columns = models.feature_columns
    index = scoring.index
    frame = pd.DataFrame(
        {
            "points_if_appearance": pd.Series(pd.NA, index=index, dtype="Float64"),
            "points_if_start": pd.Series(pd.NA, index=index, dtype="Float64"),
            "points_if_substitute": pd.Series(pd.NA, index=index, dtype="Float64"),
        },
        index=index,
    )
    scorable = complete_feature_rows(scoring, columns)
    if not bool(scorable.any()):
        return frame
    design = _design(scoring.loc[scorable], columns)
    for column, model in (
        ("points_if_appearance", models.pooled),
        ("points_if_start", models.started),
        ("points_if_substitute", models.substitute),
    ):
        frame.loc[scorable, column] = np.clip(model.predict(design), 0.0, None)
    return frame


def compose_arms(
    appearance: "pd.Series[Any]",
    conditional_start: "pd.Series[Any]",
    points: pd.DataFrame,
    *,
    training_start_rate: float,
) -> pd.DataFrame:
    """The three arms' expected points, on one row set and with one fallback rule.

    A row whose start design is incomplete has no ``q``. It keeps the uncomposed value in
    every arm rather than being dropped, so the arms differ on exactly the rows where the
    composition had something to say and are byte-identical everywhere else. Which rows those
    are is counted by the caller and belongs in the record.
    """

    probability = pd.to_numeric(appearance, errors="coerce").astype("Float64")
    ratio = pd.to_numeric(conditional_start, errors="coerce").astype("Float64")
    pooled = points["points_if_appearance"].astype("Float64")
    started = points["points_if_start"].astype("Float64")
    substitute = points["points_if_substitute"].astype("Float64")

    uncomposed = probability * pooled
    split_ready = probability.notna() & started.notna() & substitute.notna()
    rate = float(training_start_rate)
    split = probability * (rate * started + (1.0 - rate) * substitute)
    composed = probability * (ratio * started + (1.0 - ratio) * substitute)
    return pd.DataFrame(
        {
            "uncomposed": uncomposed,
            "state_split": split.where(split_ready, uncomposed),
            "composed": composed.where(split_ready & ratio.notna(), uncomposed),
        },
        index=points.index,
    )


def points_reading(forecast: "pd.Series[Any]", realized: "pd.Series[Any]") -> dict[str, object]:
    """Rows, mean error and mean absolute error, over the rows both sides are present on."""

    values = pd.to_numeric(forecast, errors="coerce").astype("float64")
    outcomes = pd.to_numeric(realized, errors="coerce").astype("float64")
    scored = values.notna() & outcomes.notna()
    if not bool(scored.any()):
        return {"rows": 0}
    error = values.loc[scored] - outcomes.loc[scored]
    return {
        "rows": int(scored.sum()),
        "mean_forecast": float(values.loc[scored].mean()),
        "mean_realized": float(outcomes.loc[scored].mean()),
        # Forecast minus realized: positive is over-forecasting, the sign the level audit uses.
        "mean_error": float(error.mean()),
        "mean_absolute_error": float(error.abs().mean()),
    }


__all__ = [
    "ARM_NAMES",
    "PARTICIPATION_COMPOSITION_CONTRACT_VERSION",
    "STATE_LABELS",
    "StatePointsModels",
    "compose_arms",
    "fit_state_points",
    "points_reading",
    "realized_state",
    "state_points",
]

"""Deterministic control component models: appearance, conditional minutes, conditional points.

These are the *control* arm of Phase C -- simple, explainable, fixed. No model selection, no
hyperparameter search, no optional evidence. Their job is to be a reproducible reference the
evaluation side can measure a candidate against, so every choice here is declared rather
than searched.

Three estimators are fitted, and one is deliberately not:

* appearance -- regularized logistic regression over every row with complete features;
* conditional minutes -- ridge regression over rows where the player appeared;
* conditional points -- ridge regression over the same rows;
* **start -- not fitted.** The pre-registration requires
  ``p_start = p_appearance * q_start_given_appearance`` and forbids composing two
  independently fitted probabilities, so the admissible start model is a *conditional*
  one; and its label does not exist in this panel
  (:mod:`squadopt.features.component_targets`). ``start_probability`` is therefore missing,
  not zero.

Scaling is inside the estimator pipeline, so it is fitted on the training rows and only
those. The pre-registration requires exactly that: preprocessing is fitted on rows strictly
earlier than the decision being scored.

**Where the bounds are applied matters.** ``prediction.components`` *refuses* a conditional
minutes value above ``90 * fixture_count`` and *refuses* a composed expected-points value
below zero -- it does not clip them. So the clipping happens here, at the model's own
output boundary, and the unclipped conditional points value is kept beside it as
``raw_expected_points_if_appearance`` for diagnostics. The frozen component contract is not
touched.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression, Ridge  # type: ignore[import-untyped]
from sklearn.pipeline import Pipeline, make_pipeline  # type: ignore[import-untyped]
from sklearn.preprocessing import StandardScaler  # type: ignore[import-untyped]

from squadopt.prediction.component_dataset import FIXTURE_COUNT_COLUMN
from squadopt.prediction.components import (
    COMPONENT_MODEL_ROUTE,
    DIRECT_CONTROL_ROUTE,
    EVIDENCE_NOT_REQUESTED,
)
from squadopt.prediction.config import PredictionConfigurationError

COMPONENT_MODEL_VERSION: Final = "phase_c_control_components_v1"

# One full match, and the physical ceiling a conditional minutes prediction is clipped to
# once multiplied by the gameweek's fixture count.
MINUTES_PER_FIXTURE: Final = 90.0

# Fixed for reproducibility. `lbfgs` and `cholesky` are deterministic given the data, and
# the seed is set anyway so a future solver change cannot quietly introduce a draw.
RANDOM_STATE: Final = 0

COMPONENT_PREDICTION_COLUMNS: Final = (
    "appearance_probability",
    "q_start_given_appearance",
    "start_probability",
    "expected_minutes_if_appearance",
    "raw_expected_points_if_appearance",
    "expected_points_if_appearance",
    "control_expected_points",
    "composition_route",
    "evidence_status",
)


@dataclass(frozen=True, slots=True)
class ComponentModelConfig:
    """Declared, unsearched parameters for the three control estimators.

    ``minimum_training_rows`` guards the conditional estimators as well as the appearance
    one: a ridge fitted on a handful of rows produces a number, and a number produced that
    way is worse than an honest refusal because nothing downstream can tell them apart.
    """

    appearance_regularization: float = 1.0
    appearance_max_iterations: int = 1000
    minutes_alpha: float = 1.0
    points_alpha: float = 1.0
    minimum_training_rows: int = 200

    def __post_init__(self) -> None:
        for name in ("appearance_regularization", "minutes_alpha", "points_alpha"):
            value = getattr(self, name)
            if not isinstance(value, float | int) or isinstance(value, bool) or value <= 0:
                raise PredictionConfigurationError(f"{name} must be a positive number.")
        for name in ("appearance_max_iterations", "minimum_training_rows"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise PredictionConfigurationError(f"{name} must be a positive integer.")


@dataclass(frozen=True, slots=True)
class FittedComponentModels:
    """The three fitted estimators, with the rows each was fitted on."""

    appearance: Pipeline
    minutes: Pipeline
    points: Pipeline
    feature_columns: tuple[str, ...]
    appearance_rows: int
    conditional_rows: int
    model_version: str = COMPONENT_MODEL_VERSION


def _design(frame: pd.DataFrame, feature_columns: Sequence[str]) -> pd.DataFrame:
    missing = [column for column in feature_columns if column not in frame.columns]
    if missing:
        raise PredictionConfigurationError(f"Frame is missing feature columns: {missing!r}.")
    # Non-numeric or absent values become NaN rather than raising, because a row that
    # cannot supply a feature is a fallback row, not a failed run. Which rows those are is
    # what `complete_feature_rows` reports.
    design: pd.DataFrame = frame.loc[:, list(feature_columns)].apply(pd.to_numeric, errors="coerce")
    return design


def complete_feature_rows(frame: pd.DataFrame, feature_columns: Sequence[str]) -> pd.Series:
    """Which rows carry every feature.

    A player's first gameweek in a season has no rolling history at all, so its features
    are missing. Missing is not imputed to zero here -- zero minutes of recent form and
    *unknown* recent form are different claims, and a model cannot separate them
    afterwards. Such a row gets no component prediction and says so through its route.
    """

    design = _design(frame, feature_columns)
    return design.notna().all(axis=1)


def fit_component_models(
    training: pd.DataFrame,
    *,
    feature_columns: Sequence[str],
    config: ComponentModelConfig | None = None,
) -> FittedComponentModels | None:
    """Fit the three control estimators, or return ``None`` when history is too thin.

    ``None`` is a refusal the caller must record, not a silent failure: every row it then
    produces carries the ``direct_control`` route, and the count travels in the manifest.
    """

    settings = ComponentModelConfig() if config is None else config
    if not isinstance(settings, ComponentModelConfig):
        raise PredictionConfigurationError("config must be a ComponentModelConfig.")
    if not isinstance(training, pd.DataFrame):
        raise PredictionConfigurationError("fit_component_models expects a pandas DataFrame.")
    columns = tuple(str(column) for column in feature_columns)
    if not columns:
        raise PredictionConfigurationError("At least one feature column is required.")

    usable = training.loc[complete_feature_rows(training, columns)]
    appearance_target = pd.to_numeric(usable["appearance_target"], errors="raise")
    if len(usable) < settings.minimum_training_rows:
        return None
    # A logistic regression needs both outcomes present; a single-class fold cannot
    # produce a probability and must not be papered over with a constant.
    if appearance_target.nunique(dropna=True) < 2:
        return None

    appeared = usable.loc[appearance_target.astype("int64") == 1]
    conditional = appeared.loc[
        pd.to_numeric(appeared["minutes_target"], errors="coerce").notna()
        & pd.to_numeric(appeared["points_target"], errors="coerce").notna()
    ]
    if len(conditional) < settings.minimum_training_rows:
        return None

    appearance_model = make_pipeline(
        StandardScaler(),
        LogisticRegression(
            C=settings.appearance_regularization,
            max_iter=settings.appearance_max_iterations,
            solver="lbfgs",
            random_state=RANDOM_STATE,
        ),
    )
    appearance_model.fit(_design(usable, columns), appearance_target.astype("int64"))

    minutes_model = make_pipeline(
        StandardScaler(), Ridge(alpha=settings.minutes_alpha, solver="cholesky")
    )
    minutes_model.fit(
        _design(conditional, columns),
        pd.to_numeric(conditional["minutes_target"], errors="raise").astype("float64"),
    )

    points_model = make_pipeline(
        StandardScaler(), Ridge(alpha=settings.points_alpha, solver="cholesky")
    )
    points_model.fit(
        _design(conditional, columns),
        pd.to_numeric(conditional["points_target"], errors="raise").astype("float64"),
    )

    return FittedComponentModels(
        appearance=appearance_model,
        minutes=minutes_model,
        points=points_model,
        feature_columns=columns,
        appearance_rows=len(usable),
        conditional_rows=len(conditional),
    )


def predict_components(
    models: FittedComponentModels | None,
    scoring: pd.DataFrame,
    *,
    feature_columns: Sequence[str],
) -> pd.DataFrame:
    """Predict the components for one decision's rows.

    Returns one row per input row, in the input's order, carrying
    :data:`COMPONENT_PREDICTION_COLUMNS`. A row is either a ``component_model`` row with
    every component present, or a ``direct_control`` row with all of them missing. There
    is no partial row: half a composition is not a prediction.

    A blank gameweek overrides everything. ``fixture_count == 0`` yields zeros throughout,
    because historical form cannot override a known empty calendar -- the same rule the
    frozen component contract enforces.
    """

    if not isinstance(scoring, pd.DataFrame):
        raise PredictionConfigurationError("predict_components expects a pandas DataFrame.")
    columns = tuple(str(column) for column in feature_columns)
    if models is not None and models.feature_columns != columns:
        raise PredictionConfigurationError(
            "feature_columns must match the columns the models were fitted on; a design "
            f"matrix in another order is another model. Fitted {list(models.feature_columns)!r}, "
            f"asked for {list(columns)!r}."
        )
    if FIXTURE_COUNT_COLUMN not in scoring.columns:
        raise PredictionConfigurationError(
            f"Scoring frame must carry {FIXTURE_COUNT_COLUMN!r} for the minutes bound."
        )

    index = scoring.index
    fixtures = pd.to_numeric(scoring[FIXTURE_COUNT_COLUMN], errors="raise").astype("int64")
    if bool((fixtures < 0).any()):
        raise PredictionConfigurationError("fixture_count must not be negative.")

    appearance = pd.Series(pd.NA, index=index, dtype="Float64")
    minutes = pd.Series(pd.NA, index=index, dtype="Float64")
    raw_points = pd.Series(pd.NA, index=index, dtype="Float64")
    points = pd.Series(pd.NA, index=index, dtype="Float64")
    route = pd.Series(DIRECT_CONTROL_ROUTE, index=index, dtype="string")

    modelled = (
        complete_feature_rows(scoring, columns)
        if models is not None
        else pd.Series(False, index=index)
    )
    if models is not None and bool(modelled.any()):
        design = _design(scoring.loc[modelled], columns)
        probability = np.clip(models.appearance.predict_proba(design)[:, 1], 0.0, 1.0)
        ceiling = fixtures.loc[modelled].to_numpy(dtype="float64") * MINUTES_PER_FIXTURE
        conditional_minutes = np.clip(models.minutes.predict(design), 0.0, ceiling)
        conditional_points_raw = models.points.predict(design)
        conditional_points = np.clip(conditional_points_raw, 0.0, None)

        appearance.loc[modelled] = probability
        minutes.loc[modelled] = conditional_minutes
        raw_points.loc[modelled] = conditional_points_raw
        points.loc[modelled] = conditional_points
        route.loc[modelled] = COMPONENT_MODEL_ROUTE

    blank = fixtures == 0
    if bool(blank.any()):
        for series in (appearance, minutes, raw_points, points):
            series.loc[blank] = 0.0
        route.loc[blank] = COMPONENT_MODEL_ROUTE

    control = appearance * points
    return pd.DataFrame(
        {
            "appearance_probability": appearance,
            # The admissible start model is conditional -- the pre-registration requires
            # `p_start = p_appearance * q_start_given_appearance` and forbids composing two
            # independently fitted probabilities -- and its label does not exist in this
            # panel. Both halves are therefore unavailable rather than zero, and both are
            # named so a consumer finds an explicit absence instead of a missing column.
            "q_start_given_appearance": pd.Series(pd.NA, index=index, dtype="Float64"),
            "start_probability": pd.Series(pd.NA, index=index, dtype="Float64"),
            "expected_minutes_if_appearance": minutes,
            "raw_expected_points_if_appearance": raw_points,
            "expected_points_if_appearance": points,
            "control_expected_points": control,
            "composition_route": route,
            "evidence_status": pd.Series(EVIDENCE_NOT_REQUESTED, index=index, dtype="string"),
        },
        index=index,
    ).loc[:, list(COMPONENT_PREDICTION_COLUMNS)]

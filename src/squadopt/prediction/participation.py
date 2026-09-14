"""Does he start, given that he plays: the conditional half of the participation split.

The live season says the sixty-minute threshold, the second appearance point and clean-sheet
eligibility all reduce to one question. Over 1890 player-gameweeks, a starter reached sixty
minutes with probability 0.955 and a substitute with probability 0.004, so what separates a
returning starter from a likely cameo is not the shape of a minutes curve — it is which of
three states he lands in: no minutes, a substitute appearance, or a start.

**What this module fits is one of the two halves, on purpose.**
``docs/phase_c_component_model_prereg.md`` prescribes the composition:

.. code-block:: text

    p_appearance             = P(A = 1 | X)
    q_start_given_appearance = P(S = 1 | A = 1, X)
    p_start                  = p_appearance * q_start_given_appearance

and this module supplies ``q``. ``p_appearance`` keeps the estimator it already has. A single
multinomial over the three states would also produce ``p_appearance``, as the sum of its
substitute and start masses, and that number is not free to move: it reaches
``control_expected_points``, which is the promoted operational control, so re-estimating it
here would be a promotion carried out by a refactor. The three states are still what is
modelled and reported — they are reached through the factorisation the contract already
fixes, in :func:`participation_states`.

Nothing is ordered. A rested first-choice player and a fringe squad player land in the same
state for opposite reasons, so a single latent index cannot move them together, and
goalkeepers break such a model a second way: their substitute state is close to unreachable
rather than merely rare. The factorisation imposes no ordering either.

**Team strength is a control, not an extra.** Strong clubs have deep benches, substitute
earlier and win anyway, so a rotation model without that term attributes the squad's quality
to the player's role. It is built here from the frozen team key and the shifted rolling
primitive the feature layer already owns, so it sees only gameweeks before the one it
describes.

The population this may be fitted on is declared in ``docs/participation_model_prereg.md``
and reaches the panel through ``features/component_targets.py``. This module does not widen
it: rows whose ``start_target`` is missing are not trained on and are not scored with a
guess.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression  # type: ignore[import-untyped]
from sklearn.pipeline import Pipeline  # type: ignore[import-untyped]
from sklearn.preprocessing import StandardScaler  # type: ignore[import-untyped]

from squadopt.data.schema import TEAM_GROUP_COLUMNS
from squadopt.features.rolling import shifted_team_rolling_mean
from squadopt.prediction.component_models import complete_feature_rows
from squadopt.prediction.config import PredictionConfigurationError

#: Identifies this estimator in a manifest. It moves when the fitted object's meaning moves,
#: which is what lets a later reader tell two runs apart without re-deriving either.
CONDITIONAL_START_MODEL_VERSION: Final = "participation_conditional_start_v1"

#: The team-strength control's column name in the design matrix.
TEAM_STRENGTH_COLUMN: Final = "team_points_last_5"

#: Gameweeks of club form the control averages over. Declared, not searched.
TEAM_STRENGTH_WINDOW: Final = 5


@dataclass(frozen=True, slots=True)
class ParticipationModelConfig:
    """Declared, unsearched parameters for the conditional start estimator.

    ``minimum_training_rows`` is a refusal rather than a warning. A logistic regression
    fitted on a handful of appeared rows still returns probabilities, and a probability
    produced that way is worse than an honest absence because nothing downstream can tell
    the two apart.
    """

    regularization: float = 1.0
    max_iterations: int = 1000
    minimum_training_rows: int = 200

    def __post_init__(self) -> None:
        if (
            not isinstance(self.regularization, float | int)
            or isinstance(self.regularization, bool)
            or self.regularization <= 0
        ):
            raise PredictionConfigurationError("regularization must be a positive number.")
        for name in ("max_iterations", "minimum_training_rows"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise PredictionConfigurationError(f"{name} must be a positive integer.")


@dataclass(frozen=True, slots=True)
class FittedStartModel:
    """The conditional start estimator and the rows it was fitted on."""

    conditional_start: Pipeline
    feature_columns: tuple[str, ...]
    training_rows: int
    model_version: str = CONDITIONAL_START_MODEL_VERSION


def attach_team_strength(
    frame: pd.DataFrame, *, window: int = TEAM_STRENGTH_WINDOW
) -> pd.DataFrame:
    """Add each row's own club's recent scoring, from gameweeks before its own.

    The player's club, not the opponent's. ``features/strength.py`` estimates the strength a
    player *faces*; the control this model needs is the strength of the squad he is competing
    for a place in, and they are different numbers with different signs.

    Computed at team grain and joined back, so every player of one club in one gameweek
    carries the same value — a club's form is a property of the club. The shift is the
    primitive's, not this function's, which is what keeps a gameweek out of its own feature.
    """

    required = (*TEAM_GROUP_COLUMNS, "gameweek", "total_points")
    missing = sorted(column for column in required if column not in frame.columns)
    if missing:
        raise PredictionConfigurationError(
            f"Team strength needs columns {missing!r}; the frame provides "
            f"{sorted(frame.columns)!r}."
        )

    totals = (
        frame.loc[:, [*TEAM_GROUP_COLUMNS, "gameweek", "total_points"]]
        .groupby([*TEAM_GROUP_COLUMNS, "gameweek"], as_index=False, sort=True)
        .agg({"total_points": "sum"})
    )
    totals[TEAM_STRENGTH_COLUMN] = shifted_team_rolling_mean(
        totals, "total_points", window, min_periods=1
    )
    joined = frame.merge(
        totals.loc[:, [*TEAM_GROUP_COLUMNS, "gameweek", TEAM_STRENGTH_COLUMN]],
        on=[*TEAM_GROUP_COLUMNS, "gameweek"],
        how="left",
        validate="many_to_one",
    )
    joined.index = frame.index
    return joined


def start_feature_columns(base: Sequence[str]) -> tuple[str, ...]:
    """The component design plus the team-strength control, in a fixed order."""

    columns = tuple(str(column) for column in base)
    if TEAM_STRENGTH_COLUMN in columns:
        return columns
    return (*columns, TEAM_STRENGTH_COLUMN)


def _design(frame: pd.DataFrame, columns: Sequence[str]) -> "np.ndarray[Any, Any]":
    return frame.loc[:, list(columns)].to_numpy(dtype="float64")


def fit_start_model(
    training: pd.DataFrame,
    *,
    feature_columns: Sequence[str],
    config: ParticipationModelConfig | None = None,
) -> FittedStartModel | None:
    """Fit ``P(S = 1 | A = 1, X)``, or refuse when the labelled population is too thin.

    ``None`` is the refusal, and it is the same shape the component fit already uses: a
    caller that receives it records an absence rather than substituting a constant.

    Only rows that appeared **and** carry a start label are fitted on. Those two conditions
    are separate: a row may have appeared in a season the archive does not label, and a
    labelled row may not have appeared. Training on either would answer a different question
    from the one the contract asks.
    """

    settings = ParticipationModelConfig() if config is None else config
    if not isinstance(settings, ParticipationModelConfig):
        raise PredictionConfigurationError("config must be a ParticipationModelConfig.")
    if not isinstance(training, pd.DataFrame):
        raise PredictionConfigurationError("fit_start_model expects a pandas DataFrame.")
    columns = tuple(str(column) for column in feature_columns)
    if not columns:
        raise PredictionConfigurationError("At least one feature column is required.")

    complete = training.loc[complete_feature_rows(training, columns)]
    appeared = pd.to_numeric(complete["appearance_target"], errors="coerce") == 1
    labelled = pd.to_numeric(complete["start_target"], errors="coerce").notna()
    usable = complete.loc[appeared & labelled]
    if len(usable) < settings.minimum_training_rows:
        return None

    target = pd.to_numeric(usable["start_target"], errors="raise").astype("int64")
    # Both outcomes must be present. A single-class population cannot produce a probability,
    # and a constant dressed as one would be indistinguishable downstream from a fit.
    if target.nunique(dropna=True) < 2:
        return None

    pipeline = Pipeline(
        [
            ("scale", StandardScaler()),
            (
                "model",
                LogisticRegression(
                    C=float(settings.regularization),
                    max_iter=int(settings.max_iterations),
                ),
            ),
        ]
    )
    pipeline.fit(_design(usable, columns), target.to_numpy(dtype="int64"))
    return FittedStartModel(
        conditional_start=pipeline,
        feature_columns=columns,
        training_rows=len(usable),
    )


def predict_start_given_appearance(
    model: FittedStartModel | None,
    scoring: pd.DataFrame,
    *,
    feature_columns: Sequence[str],
) -> "pd.Series[Any]":
    """``q`` for rows the design is complete on, and ``pd.NA`` for the rest.

    Absent rather than zero. A row the model cannot score is a row nothing is known about,
    and a zero there would say the player is certain not to start.
    """

    index = scoring.index
    conditional = pd.Series(pd.NA, index=index, dtype="Float64")
    if model is None:
        return conditional
    columns = tuple(str(column) for column in feature_columns)
    scorable = complete_feature_rows(scoring, columns)
    if not bool(scorable.any()):
        return conditional
    probability = model.conditional_start.predict_proba(_design(scoring.loc[scorable], columns))
    conditional.loc[scorable] = np.clip(probability[:, 1], 0.0, 1.0)
    return conditional


def participation_states(
    appearance: "pd.Series[Any]", conditional_start: "pd.Series[Any]"
) -> pd.DataFrame:
    """The three state probabilities, as the standing contract defines them.

    .. code-block:: text

        p_none       = 1 - p_appearance
        p_substitute = p_appearance * (1 - q)
        p_start      = p_appearance * q

    They sum to one by algebra, and ``p_start <= p_appearance`` holds because ``q`` lies in
    ``[0, 1]`` — neither needs a repair step, which is what the contract means by
    representing the relation structurally rather than clipping after prediction.

    A missing half makes all three missing. Filling one from the other would state a
    participation split nobody estimated.
    """

    probability = pd.to_numeric(appearance, errors="coerce").astype("Float64")
    ratio = pd.to_numeric(conditional_start, errors="coerce").astype("Float64")
    known = probability.notna() & ratio.notna()
    blank = pd.Series(pd.NA, index=probability.index, dtype="Float64")
    return pd.DataFrame(
        {
            "p_none": (1.0 - probability).where(known, blank),
            "p_substitute": (probability * (1.0 - ratio)).where(known, blank),
            "p_start": (probability * ratio).where(known, blank),
        },
        index=probability.index,
    )


__all__ = [
    "CONDITIONAL_START_MODEL_VERSION",
    "TEAM_STRENGTH_COLUMN",
    "TEAM_STRENGTH_WINDOW",
    "FittedStartModel",
    "ParticipationModelConfig",
    "attach_team_strength",
    "fit_start_model",
    "participation_states",
    "predict_start_given_appearance",
    "start_feature_columns",
]

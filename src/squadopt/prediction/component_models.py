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
  one. Start labels now exist in :mod:`squadopt.features.component_targets`, and the
  separate :mod:`squadopt.prediction.participation` experiment fits that conditional
  estimator. It has not been promoted into this frozen control (see
  ``docs/participation_calibration.md``). This control's ``start_probability`` remains
  missing, not zero; label availability is not a promotion decision.

Scaling is inside the estimator pipeline, so it is fitted on the training rows and only
those. The pre-registration requires exactly that: preprocessing is fitted on rows strictly
earlier than the decision being scored.

**Where the bounds are applied matters.** ``prediction.components`` *refuses* a conditional
minutes value above ``90 * fixture_count`` and *refuses* a composed expected-points value
below zero -- it does not clip them. So the clipping happens here, at the model's own
output boundary, and the unclipped conditional points value is kept beside it as
``raw_expected_points_if_appearance`` for diagnostics. The frozen component contract is not
touched.

**Training-row weighting.** The equal-weight fit above is the control. The one declared
alternative is :class:`SeasonAgeWeighting`: every training row is weighted by
``0.5 ** (prediction season start year - row season start year)``, so the season being
predicted weighs 1, the season before it 0.5, the one before that 0.25. The weights are
normalized to a mean of one inside each fitted subset and handed to the scaler and the
estimator alike, so the same rows are weighted the same way at every step. Nothing else
changes between the two fits -- same features, targets and hyperparameters -- and a
weighted fit carries its own model version. The half-life is a declared constant, not a
searched one.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

import numpy as np
import numpy.typing as npt
import pandas as pd
from sklearn.ensemble import (  # type: ignore[import-untyped]
    HistGradientBoostingClassifier,
    HistGradientBoostingRegressor,
)
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

# The single declared season-age weighting candidate. Same features, targets and
# hyperparameters as the control; only the training rows are weighted by
# ``0.5 ** (prediction season start year - row season start year)``, normalized to a mean
# of one inside each fitted subset. The half-life is fixed here, not searched, and a fit
# that uses it carries its own model version so a consumer cannot mistake it for the
# equal-weight control.
SEASON_WEIGHTED_MODEL_VERSION: Final = "phase_c_components_season_half_life_v1"

# The declared gradient-boosting candidate: the same features, targets, rows and routes as
# the control, with each of the three estimators replaced by a histogram gradient-boosted
# tree ensemble whose parameters are fixed below and never searched. Equal weighting only;
# a fit under this estimator carries its own model version so a consumer cannot mistake it
# for the linear control.
GRADIENT_BOOSTING_MODEL_VERSION: Final = "phase_c_control_components_gbm_v1"
# The fourth declared Phase C v2 development candidate, after the decision-level reading of
# the boosted pair above: the linear appearance and minutes estimators kept, only the
# conditional points estimator boosted. The decision-level probes found the loss of the full
# boosted pair in its appearance probability and the gain in its conditional points; this
# arm keeps the one and takes the other.
GRADIENT_BOOSTING_POINTS_MODEL_VERSION: Final = "phase_c_control_components_gbm_points_v1"
# The fourth declared candidate (`docs/research/moe_mixture_prereg.md`): the appearance
# estimator kept, each conditional ridge replaced by a gated mixture of two ridge experts.
# The gate is the served appearance estimator's logistic regression fitted on a supervised
# regime label of the training rows; the expected value is the gate-weighted mean and the
# predictive distribution the gated mixture of the experts' Gaussian residuals. The regime
# rules and the scale floors below are constants of the declaration, never searched.
MIXTURE_MODEL_VERSION: Final = "phase_c_control_components_mixture_v1"
# The regime-gated candidate (mixture-of-experts line 3, `docs/research/moe_regime_prereg.md`):
# one served-pair expert set per declared regime (fixture regime by rule era), mixed by a
# multinomial logistic gate on the v1 features plus the regime terms. Equal weighting only;
# the constants are the control's own and the regime boundaries are declared below.
REGIME_MODEL_VERSION: Final = "phase_c_control_components_regime_v1"
LINEAR_ESTIMATOR: Final = "linear"
GRADIENT_BOOSTING_ESTIMATOR: Final = "gradient_boosting"
GRADIENT_BOOSTING_POINTS_ESTIMATOR: Final = "gradient_boosting_points"
MIXTURE_ESTIMATOR: Final = "mixture"
REGIME_ESTIMATOR: Final = "regime"
ESTIMATORS: Final = (
    LINEAR_ESTIMATOR,
    GRADIENT_BOOSTING_ESTIMATOR,
    GRADIENT_BOOSTING_POINTS_ESTIMATOR,
    MIXTURE_ESTIMATOR,
    REGIME_ESTIMATOR,
)
# A training row is in the `full` minutes regime when it played at least the 60-minute
# appearance threshold of the scoring rules in every fixture of its gameweek, and in the
# `return` points regime when it scored the two points of a full appearance plus at least two
# more (a clean sheet, a goal, an assist or bonus).
MINUTES_FULL_THRESHOLD_PER_FIXTURE: Final = 60.0
POINTS_RETURN_THRESHOLD: Final = 4.0
# Residual scales are floored so a near-constant expert cannot claim a point mass.
MINUTES_SCALE_FLOOR: Final = 1.0
POINTS_SCALE_FLOOR: Final = 0.5
# The predictive family each estimator writes to the distribution sidecar.
SINGLE_GAUSSIAN_FAMILY: Final = "gaussian_1"
MIXTURE_FAMILY: Final = "gaussian_mixture_2"
DISTRIBUTION_COLUMNS: Final = (
    "distribution_family",
    "minutes_gate",
    "minutes_mean_low",
    "minutes_mean_high",
    "minutes_scale_low",
    "minutes_scale_high",
    "points_gate",
    "points_mean_low",
    "points_mean_high",
    "points_scale_low",
    "points_scale_high",
)

# The regimes of the gated candidate. A row's label is the cross of its fixture regime
# (single or double gameweek; a blank gameweek is the contract's zero and reaches no fit)
# and its rule era (seasons from 2025-26 carry the defensive-contribution and keeper
# rules). The season-age term is the third regime term: an input of the gate, never a
# label and never a sample weight.
SEASON_COLUMN: Final = "season"
DEFCON_ERA_FIRST_START_YEAR: Final = 2025
SINGLE_PRE_DEFCON_REGIME: Final = "single_pre_defcon"
DOUBLE_PRE_DEFCON_REGIME: Final = "double_pre_defcon"
SINGLE_DEFCON_REGIME: Final = "single_defcon"
DOUBLE_DEFCON_REGIME: Final = "double_defcon"
REGIME_LABELS: Final = (
    SINGLE_PRE_DEFCON_REGIME,
    DOUBLE_PRE_DEFCON_REGIME,
    SINGLE_DEFCON_REGIME,
    DOUBLE_DEFCON_REGIME,
)
REGIME_DOUBLE_TERM: Final = "regime_double_fixture"
REGIME_DEFCON_TERM: Final = "regime_defcon_era"
REGIME_SEASON_AGE_TERM: Final = "regime_season_age"
REGIME_GATE_TERMS: Final = (REGIME_DOUBLE_TERM, REGIME_DEFCON_TERM, REGIME_SEASON_AGE_TERM)
EQUAL_WEIGHTING: Final = "equal_weights_v1"
SEASON_HALF_LIFE_WEIGHTING: Final = "season_half_life_0.5_v1"
SEASON_WEIGHT_BASE: Final = 0.5

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
    # ``estimator`` selects the linear control or the declared gradient-boosting candidate.
    # The boosting parameters below are constants of the declaration: a tree ensemble with
    # a fixed number of rounds, no early stopping (so the same rows give the same model) and
    # a leaf size large enough that a fold of a few hundred players cannot be memorized.
    estimator: str = LINEAR_ESTIMATOR
    boosting_learning_rate: float = 0.05
    boosting_iterations: int = 300
    boosting_max_leaf_nodes: int = 31
    boosting_min_samples_leaf: int = 100
    boosting_l2_regularization: float = 1.0

    def __post_init__(self) -> None:
        for name in (
            "appearance_regularization",
            "minutes_alpha",
            "points_alpha",
            "boosting_learning_rate",
            "boosting_l2_regularization",
        ):
            value = getattr(self, name)
            if not isinstance(value, float | int) or isinstance(value, bool) or value <= 0:
                raise PredictionConfigurationError(f"{name} must be a positive number.")
        for name in (
            "appearance_max_iterations",
            "minimum_training_rows",
            "boosting_iterations",
            "boosting_max_leaf_nodes",
            "boosting_min_samples_leaf",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise PredictionConfigurationError(f"{name} must be a positive integer.")
        if self.estimator not in ESTIMATORS:
            raise PredictionConfigurationError(
                f"estimator must be one of {ESTIMATORS}, got {self.estimator!r}."
            )


@dataclass(frozen=True, slots=True)
class GatedMixtureRegressor:
    """A gated mixture of two ridge experts over one conditional target.

    ``gate`` is a logistic regression for the high regime (``full`` minutes, a points
    ``return``), ``low`` and ``high`` the ridge experts fitted on each regime's rows alone,
    and the scales the experts' residual standard deviations on their own rows. ``predict``
    returns the gate-weighted mean, so the fitted model reads like the ridge it replaces;
    ``parameters`` returns what the mean hides, the two means and the gate weight, for the
    distribution sidecar.
    """

    gate: Pipeline
    low: Pipeline
    high: Pipeline
    low_scale: float
    high_scale: float
    low_rows: int
    high_rows: int

    def high_weight(self, design: pd.DataFrame) -> npt.NDArray[np.float64]:
        weight: npt.NDArray[np.float64] = np.clip(
            self.gate.predict_proba(design)[:, 1], 0.0, 1.0
        ).astype("float64")
        return weight

    def parameters(
        self, design: pd.DataFrame
    ) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64], npt.NDArray[np.float64]]:
        """The gate weight of the high expert and the two expert means, in the input order."""

        weight = self.high_weight(design)
        low = np.asarray(self.low.predict(design), dtype="float64")
        high = np.asarray(self.high.predict(design), dtype="float64")
        return weight, low, high

    def predict(self, design: pd.DataFrame) -> npt.NDArray[np.float64]:
        weight, low, high = self.parameters(design)
        mean: npt.NDArray[np.float64] = weight * high + (1.0 - weight) * low
        return mean


@dataclass(frozen=True, slots=True)
class FittedComponentModels:
    """The three fitted estimators, with the rows each was fitted on.

    ``season_weights`` records the declared, un-normalized weight of every training season
    that reached the fit, so a manifest can show which rows counted for how much without
    re-deriving the rule. Under equal weighting every season weighs 1.

    ``minutes_scale`` and ``points_scale`` are the residual standard deviations of the two
    linear conditional estimators on their training rows (floored), the single Gaussian the
    mixture candidate's predictive distribution is scored against. They are missing for the
    boosted arms, which declare no distribution.
    """

    appearance: "Pipeline | RegimeMixture"
    minutes: "Pipeline | GatedMixtureRegressor | RegimeMixture"
    points: "Pipeline | GatedMixtureRegressor | RegimeMixture"
    feature_columns: tuple[str, ...]
    appearance_rows: int
    conditional_rows: int
    model_version: str = COMPONENT_MODEL_VERSION
    weighting: str = EQUAL_WEIGHTING
    season_weights: tuple[tuple[str, float], ...] = ()
    estimator: str = LINEAR_ESTIMATOR
    minutes_scale: float | None = None
    points_scale: float | None = None
    # The season the fit predicts; only the regime candidate needs it, for the season-age
    # term of its gate. ``None`` for every other estimator.
    target_season: str | None = None


_SEASON_LABEL: Final = re.compile(r"(?P<start>\d{4})-(?P<end>\d{2})")


def season_start_year(season: object) -> int:
    """The start year of a canonical ``YYYY-YY`` season label, refusing anything else."""

    if not isinstance(season, str) or _SEASON_LABEL.fullmatch(season) is None:
        raise PredictionConfigurationError(
            f"season must be a canonical YYYY-YY label, got {season!r}."
        )
    start = int(season[:4])
    if int(season[5:]) != (start + 1) % 100:
        raise PredictionConfigurationError(f"season label {season!r} does not span two years.")
    return start


@dataclass(frozen=True, slots=True)
class SeasonAgeWeighting:
    """The declared season-age weighting rule, bound to the season being predicted.

    A rule rather than a bag of weights, so the fit can compute the weights from the
    training rows' own season labels and record them: a caller cannot hand in weights that
    silently belong to a different row set.
    """

    target_season: str

    def __post_init__(self) -> None:
        season_start_year(self.target_season)

    @property
    def label(self) -> str:
        return SEASON_HALF_LIFE_WEIGHTING

    @property
    def model_version(self) -> str:
        return SEASON_WEIGHTED_MODEL_VERSION

    def season_weight(self, season: str) -> float:
        """The un-normalized weight of one training season under this rule."""

        age = season_start_year(self.target_season) - season_start_year(season)
        if age < 0:
            raise PredictionConfigurationError(
                f"Training season {season!r} lies after the prediction season "
                f"{self.target_season!r}; that is a leak, not a weighting question."
            )
        return float(SEASON_WEIGHT_BASE**age)


def season_age_weights(seasons: pd.Series, *, weighting: SeasonAgeWeighting) -> pd.Series:
    """Un-normalized row weights, aligned to ``seasons``' index, under the declared rule."""

    if not isinstance(seasons, pd.Series):
        raise PredictionConfigurationError("seasons must be a pandas Series of season labels.")
    if bool(seasons.isna().any()):
        raise PredictionConfigurationError("Every training row must carry a season label.")
    by_season = {str(season): weighting.season_weight(str(season)) for season in seasons.unique()}
    weights = seasons.astype("string").map(by_season)
    return pd.Series(weights.to_numpy(dtype="float64"), index=seasons.index, dtype="float64")


def normalize_weights(weights: pd.Series) -> pd.Series:
    """Rescale positive weights to a mean of one over exactly the rows given.

    The estimators' regularization is declared against unweighted row counts, so weights
    whose mean is not one would quietly change how strong that regularization is. A
    non-positive or non-finite weight is refused: excluding a row is the caller's decision
    and has to be visible as one.
    """

    if not isinstance(weights, pd.Series) or weights.empty:
        raise PredictionConfigurationError("weights must be a non-empty pandas Series.")
    values = pd.to_numeric(weights, errors="raise").astype("float64")
    if not bool(np.isfinite(values.to_numpy()).all()) or bool((values <= 0.0).any()):
        raise PredictionConfigurationError("Every weight must be a finite positive number.")
    return values / float(values.mean())


def _season_start_years(seasons: pd.Series) -> pd.Series:
    """The start year of every row's season label, refusing a missing or malformed one."""

    if bool(seasons.isna().any()):
        raise PredictionConfigurationError("Every row must carry a season label.")
    labels = seasons.astype("string")
    by_season = {str(season): season_start_year(str(season)) for season in labels.unique()}
    return pd.Series(labels.map(by_season).to_numpy(dtype="int64"), index=seasons.index)


def regime_labels(frame: pd.DataFrame) -> pd.Series:
    """The declared regime label of every row: fixture regime by rule era.

    ``fixture_count >= 2`` is ``double``, ``1`` is ``single``; a blank gameweek is the
    contract's zero and must not reach a fit, so it is refused here rather than labelled.
    """

    for column in (SEASON_COLUMN, FIXTURE_COUNT_COLUMN):
        if column not in frame.columns:
            raise PredictionConfigurationError(
                f"The regime candidate needs the {column!r} column on every row."
            )
    fixtures = pd.to_numeric(frame[FIXTURE_COUNT_COLUMN], errors="raise").astype("int64")
    if bool((fixtures < 1).any()):
        raise PredictionConfigurationError(
            "A blank gameweek is the contract's zero, not a regime; it must not reach a fit."
        )
    double = fixtures.to_numpy() >= 2
    defcon = _season_start_years(frame[SEASON_COLUMN]).to_numpy() >= DEFCON_ERA_FIRST_START_YEAR
    labels = np.where(
        defcon,
        np.where(double, DOUBLE_DEFCON_REGIME, SINGLE_DEFCON_REGIME),
        np.where(double, DOUBLE_PRE_DEFCON_REGIME, SINGLE_PRE_DEFCON_REGIME),
    )
    return pd.Series(labels, index=frame.index, dtype="string")


def regime_design(
    frame: pd.DataFrame, feature_columns: Sequence[str], *, target_season: str
) -> pd.DataFrame:
    """The gate's design: the v1 features plus the three declared regime terms.

    The season-age term is ``target season start year - row season start year``; it is
    zero for every scoring row and positive for the earlier seasons' training rows. A
    training row from a season after the target season is refused as a leak.
    """

    design = _design(frame, feature_columns)
    labels = regime_labels(frame)
    ages = season_start_year(target_season) - _season_start_years(frame[SEASON_COLUMN])
    if bool((ages < 0).any()):
        raise PredictionConfigurationError(
            f"A row lies after the prediction season {target_season!r}; that is a leak."
        )
    design[REGIME_DOUBLE_TERM] = (
        labels.isin((DOUBLE_PRE_DEFCON_REGIME, DOUBLE_DEFCON_REGIME)).to_numpy().astype("float64")
    )
    design[REGIME_DEFCON_TERM] = (
        labels.isin((SINGLE_DEFCON_REGIME, DOUBLE_DEFCON_REGIME)).to_numpy().astype("float64")
    )
    design[REGIME_SEASON_AGE_TERM] = ages.to_numpy(dtype="float64")
    return design


@dataclass(frozen=True, slots=True)
class RegimeExpert:
    """One regime's served pair, fitted on that regime's rows only."""

    label: str
    appearance: Pipeline
    minutes: Pipeline
    points: Pipeline
    appearance_rows: int
    conditional_rows: int


@dataclass(frozen=True, slots=True)
class RegimeMixture:
    """One component of the regime-gated candidate: the gate-weighted mean of the experts.

    The gate is shared by the three components and is ``None`` when the fold's usable rows
    carried a single regime label, in which case the one expert takes all the mass. Gate
    mass on a regime whose expert is absent is dropped and the rest renormalized, so a row
    of a thin regime is scored by the experts that exist, in the gate's proportions.
    """

    component: str
    feature_columns: tuple[str, ...]
    experts: tuple[RegimeExpert, ...]
    gate: Pipeline | None
    gate_classes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.component not in ("appearance", "minutes", "points"):
            raise PredictionConfigurationError(f"Unknown component {self.component!r}.")
        if not self.experts:
            raise PredictionConfigurationError("A regime mixture needs at least one expert.")

    def gate_weights(self, design: pd.DataFrame) -> npt.NDArray[np.float64]:
        """One row of weights per design row, over the present experts, summing to one."""

        rows = len(design)
        if self.gate is None or len(self.experts) == 1:
            weights = np.zeros((rows, len(self.experts)), dtype="float64")
            weights[:, 0] = 1.0
            return weights
        columns = [*self.feature_columns, *REGIME_GATE_TERMS]
        probabilities = np.asarray(self.gate.predict_proba(design.loc[:, columns]), dtype="float64")
        position = {label: index for index, label in enumerate(self.gate_classes)}
        weights = np.column_stack(
            [
                probabilities[:, position[expert.label]]
                if expert.label in position
                else np.zeros(rows, dtype="float64")
                for expert in self.experts
            ]
        )
        totals = weights.sum(axis=1, keepdims=True)
        # A logistic gate never puts exactly zero on a present class; the fallback keeps
        # the arithmetic defined if it ever did.
        weights = np.where(totals > 0.0, weights / np.where(totals > 0.0, totals, 1.0), 1.0)
        return np.asarray(weights / weights.sum(axis=1, keepdims=True), dtype="float64")

    def _expert_outputs(self, design: pd.DataFrame) -> npt.NDArray[np.float64]:
        features = design.loc[:, list(self.feature_columns)]
        outputs = []
        for expert in self.experts:
            if self.component == "appearance":
                outputs.append(np.asarray(expert.appearance.predict_proba(features))[:, 1])
            elif self.component == "minutes":
                outputs.append(np.asarray(expert.minutes.predict(features)))
            else:
                outputs.append(np.asarray(expert.points.predict(features)))
        return np.column_stack(outputs).astype("float64")

    def predict(self, design: pd.DataFrame) -> npt.NDArray[np.float64]:
        """The gate-weighted mean of the experts' outputs, one value per row."""

        weights = self.gate_weights(design)
        return np.asarray((weights * self._expert_outputs(design)).sum(axis=1), dtype="float64")

    def predict_proba(self, design: pd.DataFrame) -> npt.NDArray[np.float64]:
        """The appearance mixture in scikit-learn's two-column shape."""

        if self.component != "appearance":
            raise PredictionConfigurationError("Only the appearance mixture is a probability.")
        positive = np.clip(self.predict(design), 0.0, 1.0)
        return np.column_stack([1.0 - positive, positive])


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
    weighting: SeasonAgeWeighting | None = None,
    target_season: str | None = None,
) -> FittedComponentModels | None:
    """Fit the three control estimators, or return ``None`` when history is too thin.

    ``None`` is a refusal the caller must record, not a silent failure: every row it then
    produces carries the ``direct_control`` route, and the count travels in the manifest.

    With ``weighting`` the same estimators are fitted on the same rows under the declared
    season-age weights; without it the fit is the equal-weight control, unchanged.

    ``target_season`` is read by the regime candidate alone, for the season-age term of
    its gate; the other estimators ignore it.
    """

    settings = ComponentModelConfig() if config is None else config
    if not isinstance(settings, ComponentModelConfig):
        raise PredictionConfigurationError("config must be a ComponentModelConfig.")
    if not isinstance(training, pd.DataFrame):
        raise PredictionConfigurationError("fit_component_models expects a pandas DataFrame.")
    columns = tuple(str(column) for column in feature_columns)
    if not columns:
        raise PredictionConfigurationError("At least one feature column is required.")

    boosted = settings.estimator == GRADIENT_BOOSTING_ESTIMATOR
    boosted_points = settings.estimator == GRADIENT_BOOSTING_POINTS_ESTIMATOR
    mixture = settings.estimator == MIXTURE_ESTIMATOR
    regime = settings.estimator == REGIME_ESTIMATOR
    if (boosted or boosted_points or regime) and weighting is not None:
        raise PredictionConfigurationError(
            "The candidate estimators are declared under equal weighting only."
        )
    if regime and target_season is None:
        raise PredictionConfigurationError(
            "The regime candidate needs the target season for its season-age term."
        )
    if mixture and weighting is not None:
        raise PredictionConfigurationError(
            "The mixture candidate is declared under equal weighting only."
        )

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

    # The weights are computed from each subset's own season labels and normalized within
    # that subset, so the appearance fit and the conditional fits each see a mean weight of
    # one over exactly the rows they are fitted on.
    if weighting is None:
        appearance_fit: dict[str, npt.NDArray[np.float64]] = {}
        minutes_fit: dict[str, npt.NDArray[np.float64]] = {}
        points_fit: dict[str, npt.NDArray[np.float64]] = {}
        season_weights = tuple(
            (str(season), 1.0) for season in sorted(usable["season"].astype("string").unique())
        )
    else:
        if not isinstance(weighting, SeasonAgeWeighting):
            raise PredictionConfigurationError("weighting must be a SeasonAgeWeighting.")
        usable_weights = normalize_weights(
            season_age_weights(usable["season"], weighting=weighting)
        ).to_numpy(dtype="float64")
        conditional_weights = normalize_weights(
            season_age_weights(conditional["season"], weighting=weighting)
        ).to_numpy(dtype="float64")
        appearance_fit = {
            "standardscaler__sample_weight": usable_weights,
            "logisticregression__sample_weight": usable_weights,
        }
        minutes_fit = {
            "standardscaler__sample_weight": conditional_weights,
            "ridge__sample_weight": conditional_weights,
        }
        points_fit = dict(minutes_fit)
        season_weights = tuple(
            (str(season), weighting.season_weight(str(season)))
            for season in sorted(usable["season"].astype("string").unique())
        )

    if regime:
        assert target_season is not None
        return _fit_regime_models(
            usable,
            conditional,
            feature_columns=columns,
            settings=settings,
            target_season=target_season,
            season_weights=season_weights,
        )

    if boosted:
        appearance_model = make_pipeline(_boosted_classifier(settings))
        minutes_model = make_pipeline(_boosted_regressor(settings))
        points_model = make_pipeline(_boosted_regressor(settings))
    else:
        appearance_model = _linear_appearance(settings)
        minutes_model = _linear_ridge(settings.minutes_alpha)
        points_model = (
            make_pipeline(_boosted_regressor(settings))
            if boosted_points
            else _linear_ridge(settings.points_alpha)
        )
    appearance_model.fit(
        _design(usable, columns), appearance_target.astype("int64"), **appearance_fit
    )
    conditional_design = _design(conditional, columns)
    minutes_target = pd.to_numeric(conditional["minutes_target"], errors="raise").astype("float64")
    points_target = pd.to_numeric(conditional["points_target"], errors="raise").astype("float64")

    if mixture:
        if FIXTURE_COUNT_COLUMN not in conditional.columns:
            raise PredictionConfigurationError(
                f"The mixture candidate needs {FIXTURE_COUNT_COLUMN!r} on the training rows "
                "for its minutes regime label."
            )
        fixtures = pd.to_numeric(conditional[FIXTURE_COUNT_COLUMN], errors="raise").astype(
            "float64"
        )
        minutes_regime = (
            minutes_target.to_numpy() >= MINUTES_FULL_THRESHOLD_PER_FIXTURE * fixtures.to_numpy()
        )
        points_regime = points_target.to_numpy() >= POINTS_RETURN_THRESHOLD
        minimum_regime_rows = max(2, settings.minimum_training_rows // 4)
        minutes_mixture = _fit_gated_mixture(
            conditional_design,
            minutes_target,
            minutes_regime,
            settings=settings,
            alpha=settings.minutes_alpha,
            scale_floor=MINUTES_SCALE_FLOOR,
            minimum_regime_rows=minimum_regime_rows,
        )
        points_mixture = _fit_gated_mixture(
            conditional_design,
            points_target,
            points_regime,
            settings=settings,
            alpha=settings.points_alpha,
            scale_floor=POINTS_SCALE_FLOOR,
            minimum_regime_rows=minimum_regime_rows,
        )
        # A regime too thin to fit is refused like thin history, not filled with the ridge.
        if minutes_mixture is None or points_mixture is None:
            return None
        return FittedComponentModels(
            appearance=appearance_model,
            minutes=minutes_mixture,
            points=points_mixture,
            feature_columns=columns,
            appearance_rows=len(usable),
            conditional_rows=len(conditional),
            model_version=MIXTURE_MODEL_VERSION,
            weighting=EQUAL_WEIGHTING,
            season_weights=season_weights,
            estimator=settings.estimator,
        )

    minutes_model.fit(conditional_design, minutes_target, **minutes_fit)
    points_model.fit(conditional_design, points_target, **points_fit)
    # The linear conditional estimators declare a single Gaussian residual; the boosted arms
    # declare no distribution and carry no scale.
    minutes_scale = (
        None
        if boosted
        else _residual_scale(minutes_model, conditional_design, minutes_target, MINUTES_SCALE_FLOOR)
    )
    points_scale = (
        None
        if boosted or boosted_points
        else _residual_scale(points_model, conditional_design, points_target, POINTS_SCALE_FLOOR)
    )

    return FittedComponentModels(
        appearance=appearance_model,
        minutes=minutes_model,
        points=points_model,
        feature_columns=columns,
        appearance_rows=len(usable),
        conditional_rows=len(conditional),
        model_version=(
            GRADIENT_BOOSTING_MODEL_VERSION
            if boosted
            else GRADIENT_BOOSTING_POINTS_MODEL_VERSION
            if boosted_points
            else COMPONENT_MODEL_VERSION
            if weighting is None
            else weighting.model_version
        ),
        weighting=EQUAL_WEIGHTING if weighting is None else weighting.label,
        season_weights=season_weights,
        estimator=settings.estimator,
        minutes_scale=minutes_scale,
        points_scale=points_scale,
    )


def _residual_scale(
    model: Pipeline, design: pd.DataFrame, target: pd.Series, floor: float
) -> float:
    """The floored standard deviation (``ddof=1``) of a fitted estimator's training residuals."""

    residuals = target.to_numpy(dtype="float64") - np.asarray(
        model.predict(design), dtype="float64"
    )
    scale = float(np.std(residuals, ddof=1)) if len(residuals) > 1 else 0.0
    return max(scale, floor)


def _fit_gated_mixture(
    design: pd.DataFrame,
    target: pd.Series,
    high_regime: npt.NDArray[np.bool_],
    *,
    settings: ComponentModelConfig,
    alpha: float,
    scale_floor: float,
    minimum_regime_rows: int,
) -> GatedMixtureRegressor | None:
    """Fit one gated mixture, or return ``None`` when a regime is too thin to fit.

    The gate is the served appearance estimator (standardized logistic regression, the same
    constants) on the regime label; the experts are the served ridge (the same alpha) on each
    regime's rows alone, every row weighing 1. Nothing here is searched.
    """

    high_rows = int(high_regime.sum())
    low_rows = int(len(high_regime) - high_rows)
    if min(high_rows, low_rows) < minimum_regime_rows:
        return None
    gate = make_pipeline(
        StandardScaler(),
        LogisticRegression(
            C=settings.appearance_regularization,
            max_iter=settings.appearance_max_iterations,
            solver="lbfgs",
            random_state=RANDOM_STATE,
        ),
    )
    gate.fit(design, high_regime.astype("int64"))
    experts: list[Pipeline] = []
    scales: list[float] = []
    for mask in (~high_regime, high_regime):
        expert = make_pipeline(StandardScaler(), Ridge(alpha=alpha, solver="cholesky"))
        expert_design = design.loc[mask]
        expert_target = target.loc[mask]
        expert.fit(expert_design, expert_target)
        experts.append(expert)
        scales.append(_residual_scale(expert, expert_design, expert_target, scale_floor))
    return GatedMixtureRegressor(
        gate=gate,
        low=experts[0],
        high=experts[1],
        low_scale=scales[0],
        high_scale=scales[1],
        low_rows=low_rows,
        high_rows=high_rows,
    )


def _linear_appearance(settings: ComponentModelConfig) -> Pipeline:
    """The served appearance estimator: standardized logistic regression."""

    return make_pipeline(
        StandardScaler(),
        LogisticRegression(
            C=settings.appearance_regularization,
            max_iter=settings.appearance_max_iterations,
            solver="lbfgs",
            random_state=RANDOM_STATE,
        ),
    )


def _linear_ridge(alpha: float) -> Pipeline:
    """The served conditional estimator: standardized ridge regression."""

    return make_pipeline(StandardScaler(), Ridge(alpha=alpha, solver="cholesky"))


def _fit_regime_models(
    usable: pd.DataFrame,
    conditional: pd.DataFrame,
    *,
    feature_columns: tuple[str, ...],
    settings: ComponentModelConfig,
    target_season: str,
    season_weights: tuple[tuple[str, float], ...],
) -> FittedComponentModels | None:
    """Fit the regime experts and the shared gate on rows the control's guards admitted.

    Each regime with enough rows gets the served pair fitted on its own rows; the gate is
    a multinomial logistic regression over every usable row's regime label, on the v1
    features plus the regime terms. A fold with no fittable regime is refused like a thin
    fold, and the refusal is the caller's to record.
    """

    # A blank gameweek is the contract's zero: it enters no expert fit and no gate fit.
    usable = usable.loc[
        pd.to_numeric(usable[FIXTURE_COUNT_COLUMN], errors="raise").astype("int64") >= 1
    ]
    conditional = conditional.loc[
        pd.to_numeric(conditional[FIXTURE_COUNT_COLUMN], errors="raise").astype("int64") >= 1
    ]
    if usable.empty or conditional.empty:
        return None
    usable_labels = regime_labels(usable)
    conditional_labels = regime_labels(conditional)
    appearance_target = pd.to_numeric(usable["appearance_target"], errors="raise").astype("int64")
    experts: list[RegimeExpert] = []
    for label in REGIME_LABELS:
        regime_usable = usable.loc[(usable_labels == label).to_numpy()]
        regime_conditional = conditional.loc[(conditional_labels == label).to_numpy()]
        regime_appearance = appearance_target.loc[regime_usable.index]
        if (
            len(regime_usable) < settings.minimum_training_rows
            or regime_appearance.nunique() < 2
            or len(regime_conditional) < settings.minimum_training_rows
        ):
            continue
        appearance_model = _linear_appearance(settings)
        minutes_model = _linear_ridge(settings.minutes_alpha)
        points_model = _linear_ridge(settings.points_alpha)
        appearance_model.fit(_design(regime_usable, feature_columns), regime_appearance)
        regime_design_conditional = _design(regime_conditional, feature_columns)
        minutes_model.fit(
            regime_design_conditional,
            pd.to_numeric(regime_conditional["minutes_target"], errors="raise").astype("float64"),
        )
        points_model.fit(
            regime_design_conditional,
            pd.to_numeric(regime_conditional["points_target"], errors="raise").astype("float64"),
        )
        experts.append(
            RegimeExpert(
                label=label,
                appearance=appearance_model,
                minutes=minutes_model,
                points=points_model,
                appearance_rows=len(regime_usable),
                conditional_rows=len(regime_conditional),
            )
        )
    if not experts:
        return None

    gate_classes = tuple(label for label in REGIME_LABELS if bool((usable_labels == label).any()))
    gate: Pipeline | None = None
    if len(gate_classes) >= 2:
        gate = _linear_appearance(settings)
        gate.fit(
            regime_design(usable, feature_columns, target_season=target_season),
            usable_labels.astype("object"),
        )
        gate_classes = tuple(str(label) for label in gate[-1].classes_)

    def mixture(component: str) -> RegimeMixture:
        return RegimeMixture(
            component=component,
            feature_columns=feature_columns,
            experts=tuple(experts),
            gate=gate,
            gate_classes=gate_classes,
        )

    return FittedComponentModels(
        appearance=mixture("appearance"),
        minutes=mixture("minutes"),
        points=mixture("points"),
        feature_columns=feature_columns,
        appearance_rows=len(usable),
        conditional_rows=len(conditional),
        model_version=REGIME_MODEL_VERSION,
        weighting=EQUAL_WEIGHTING,
        season_weights=season_weights,
        estimator=REGIME_ESTIMATOR,
        target_season=target_season,
    )


def regime_expert_summary(models: FittedComponentModels) -> dict[str, dict[str, int]]:
    """Which regime experts a regime fit holds and how many rows each was fitted on."""

    if models.estimator != REGIME_ESTIMATOR or not isinstance(models.appearance, RegimeMixture):
        raise PredictionConfigurationError("regime_expert_summary expects a regime fit.")
    return {
        expert.label: {
            "appearance_rows": expert.appearance_rows,
            "conditional_rows": expert.conditional_rows,
        }
        for expert in models.appearance.experts
    }


def _boosted_classifier(settings: ComponentModelConfig) -> HistGradientBoostingClassifier:
    """The declared appearance ensemble; no early stopping, so the fit is a pure function."""

    return HistGradientBoostingClassifier(
        learning_rate=settings.boosting_learning_rate,
        max_iter=settings.boosting_iterations,
        max_leaf_nodes=settings.boosting_max_leaf_nodes,
        min_samples_leaf=settings.boosting_min_samples_leaf,
        l2_regularization=settings.boosting_l2_regularization,
        early_stopping=False,
        random_state=RANDOM_STATE,
    )


def _boosted_regressor(settings: ComponentModelConfig) -> HistGradientBoostingRegressor:
    """The declared conditional ensemble (squared error, the same constants)."""

    return HistGradientBoostingRegressor(
        loss="squared_error",
        learning_rate=settings.boosting_learning_rate,
        max_iter=settings.boosting_iterations,
        max_leaf_nodes=settings.boosting_max_leaf_nodes,
        min_samples_leaf=settings.boosting_min_samples_leaf,
        l2_regularization=settings.boosting_l2_regularization,
        early_stopping=False,
        random_state=RANDOM_STATE,
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
        scored = scoring.loc[modelled]
        if models.estimator == REGIME_ESTIMATOR:
            if models.target_season is None:
                raise PredictionConfigurationError("A regime fit must carry its target season.")
            # The gate reads the row's own regime terms beside the features. A blank row
            # is the contract's zero and is overwritten below whatever the estimators say,
            # so it is labelled single here only to keep the design matrix complete.
            blank_safe = scored.assign(
                **{FIXTURE_COUNT_COLUMN: fixtures.loc[modelled].clip(lower=1)}
            )
            design = regime_design(blank_safe, columns, target_season=models.target_season)
        else:
            design = _design(scored, columns)
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
            # independently fitted probabilities. The separately measured conditional
            # start estimator has not been promoted into this frozen control, despite
            # labels being available in supported seasons. Both halves remain missing,
            # not zero, and both are
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


def predict_component_distribution(
    models: FittedComponentModels | None,
    scoring: pd.DataFrame,
    *,
    feature_columns: Sequence[str],
) -> pd.DataFrame:
    """The predictive distribution parameters behind the conditional means, per modelled row.

    Returns :data:`DISTRIBUTION_COLUMNS` for exactly the rows :func:`predict_components`
    puts on the ``component_model`` route with a fitted model and a non-blank gameweek, in
    the input's order and under the input's index. The linear arm writes a single Gaussian
    (family ``gaussian_1``: gate 0, the low slots filled, the high slots missing); the
    mixture arm writes both experts and the gate weight of the high one (family
    ``gaussian_mixture_2``). The means are the experts' own outputs, before the public
    bounds. An arm that declares no distribution (the boosted arms) returns no rows, as does
    a fold with no fitted model.
    """

    if not isinstance(scoring, pd.DataFrame):
        raise PredictionConfigurationError("predict_component_distribution expects a DataFrame.")
    columns = tuple(str(column) for column in feature_columns)
    empty = pd.DataFrame({column: pd.Series(dtype="object") for column in DISTRIBUTION_COLUMNS})
    if models is None:
        return empty
    if models.feature_columns != columns:
        raise PredictionConfigurationError(
            "feature_columns must match the columns the models were fitted on."
        )
    if FIXTURE_COUNT_COLUMN not in scoring.columns:
        raise PredictionConfigurationError(
            f"Scoring frame must carry {FIXTURE_COUNT_COLUMN!r} to skip blank gameweeks."
        )
    fixtures = pd.to_numeric(scoring[FIXTURE_COUNT_COLUMN], errors="raise").astype("int64")
    modelled = complete_feature_rows(scoring, columns) & (fixtures > 0)
    if not bool(modelled.any()):
        return empty
    design = _design(scoring.loc[modelled], columns)
    index = design.index
    missing = pd.Series(np.nan, index=index, dtype="float64")

    def single(model: Pipeline | GatedMixtureRegressor, scale: float | None) -> dict[str, object]:
        if isinstance(model, GatedMixtureRegressor):
            weight, low, high = model.parameters(design)
            return {
                "gate": pd.Series(weight, index=index, dtype="float64"),
                "mean_low": pd.Series(low, index=index, dtype="float64"),
                "mean_high": pd.Series(high, index=index, dtype="float64"),
                "scale_low": pd.Series(model.low_scale, index=index, dtype="float64"),
                "scale_high": pd.Series(model.high_scale, index=index, dtype="float64"),
            }
        if scale is None:
            return {}
        return {
            "gate": pd.Series(0.0, index=index, dtype="float64"),
            "mean_low": pd.Series(
                np.asarray(model.predict(design), dtype="float64"), index=index, dtype="float64"
            ),
            "mean_high": missing,
            "scale_low": pd.Series(scale, index=index, dtype="float64"),
            "scale_high": missing,
        }

    minutes = single(models.minutes, models.minutes_scale)
    points = single(models.points, models.points_scale)
    if not minutes or not points:
        return empty
    family = MIXTURE_FAMILY if models.estimator == MIXTURE_ESTIMATOR else SINGLE_GAUSSIAN_FAMILY
    frame = pd.DataFrame(
        {
            "distribution_family": pd.Series(family, index=index, dtype="string"),
            **{f"minutes_{name}": series for name, series in minutes.items()},
            **{f"points_{name}": series for name, series in points.items()},
        },
        index=index,
    )
    return frame.loc[:, list(DISTRIBUTION_COLUMNS)]
